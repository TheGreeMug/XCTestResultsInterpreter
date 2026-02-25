#!/usr/bin/env python3
"""
XCResult Report -- API Server (Mac Backend)
============================================

JSON API for the split-deployment architecture:
  - Static frontend (HTML/JS) lives on cPanel (e.g. www.saitumeu.ro).
  - This API runs on a Mac behind Caddy (HTTPS), receives .xcresult.zip
    uploads, processes them in a background thread, and serves the
    resulting HTML report for auto-download.

Endpoints
---------
  POST /api/upload        Upload a zip, get back a job_id.
  GET  /api/status/<id>   Poll job progress.
  GET  /api/download/<id> Download the finished HTML report.
  POST /api/cleanup/<id>  Delete all job artefacts.
  GET  /api/health        Health / readiness check (no auth).

Requires macOS with Xcode (or Command Line Tools) for xcresulttool.
"""

import os
import sys
import shutil
import uuid
import time
import threading
import zipfile
import re
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from xcresult_gui_v6 import _process_xcresult_to_html  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32).hex()

_SERVER_DIR = Path(__file__).resolve().parent
_TMP_ROOT = _SERVER_DIR / "tmp"
UPLOAD_DIR = _TMP_ROOT / "uploads"
REPORT_DIR = _TMP_ROOT / "reports"
LOG_DIR = _TMP_ROOT / "logs"

for d in (UPLOAD_DIR, REPORT_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

MAX_CONTENT_LENGTH = 1 * 1024 * 1024 * 1024  # 1 GB
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
MAX_EXTRACTED_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB total uncompressed
MAX_CONCURRENT_JOBS = 2
JOB_TTL_SECONDS = 30 * 60
GLOBAL_DISK_CAP_BYTES = 5 * 1024 * 1024 * 1024

API_KEY = None
ALLOWED_ORIGINS: list[str] = []

_jobs: dict = {}
_jobs_lock = threading.Lock()

# ---------------------------------------------------------------------------
# CORS -- handled manually so we don't need an extra dependency
# ---------------------------------------------------------------------------

@app.after_request
def _cors_headers(response):
    origin = request.headers.get("Origin", "")
    if origin and (origin in ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "3600"
        response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
    return response


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if API_KEY is None:
            return f(*args, **kwargs)
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAFE_TEXT_RE = re.compile(r"^[A-Za-z0-9 _.,:;/\-()@#+]+$")
_MAX_FIELD_LEN = 50


def _validate_text_field(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        return value
    if len(value) > _MAX_FIELD_LEN:
        raise ValueError(f"{field_name} must be {_MAX_FIELD_LEN} characters or fewer.")
    if not _SAFE_TEXT_RE.match(value):
        raise ValueError(
            f"{field_name} contains invalid characters. "
            "Use letters, numbers, spaces, and common punctuation only."
        )
    return value


def _active_job_count() -> int:
    with _jobs_lock:
        return sum(1 for j in _jobs.values() if j["status"] == "processing")


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except Exception:
        pass
    return total


# ---------------------------------------------------------------------------
# Zip handling (safe extraction)
# ---------------------------------------------------------------------------

def _unpack_upload(file_storage, job_dir: Path) -> Path:
    """Save uploaded zip into *job_dir*, return path to the .xcresult inside."""
    filename = file_storage.filename or "upload.zip"
    safe_name = Path(filename).name
    saved = job_dir / safe_name
    file_storage.save(str(saved))

    if not zipfile.is_zipfile(str(saved)):
        raise ValueError("Not a valid zip. Upload a .zip containing a .xcresult bundle.")

    extract_dir = job_dir / "extracted"
    extract_dir.mkdir(exist_ok=True)

    with zipfile.ZipFile(str(saved), "r") as zf:
        total_size = sum(i.file_size for i in zf.infolist())
        if total_size > MAX_EXTRACTED_SIZE:
            raise ValueError(
                f"Zip contents too large ({total_size // (1024 * 1024)} MB). "
                f"Limit is {MAX_EXTRACTED_SIZE // (1024 * 1024)} MB."
            )
        for member in zf.infolist():
            member_path = Path(extract_dir / member.filename).resolve()
            if not str(member_path).startswith(str(extract_dir.resolve())):
                raise ValueError("Zip contains unsafe path entries (path traversal).")
        zf.extractall(str(extract_dir))

    saved.unlink(missing_ok=True)

    for item in extract_dir.rglob("*.xcresult"):
        if item.is_dir() or item.is_file():
            return item
    if (extract_dir / "Info.plist").exists():
        renamed = extract_dir.with_suffix(".xcresult")
        extract_dir.rename(renamed)
        return renamed
    raise ValueError(
        "Zip does not contain a .xcresult bundle. "
        "Zip the whole folder: right-click .xcresult in Finder > Compress."
    )


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------

def _process_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return

    job_dir = UPLOAD_DIR / job_id
    out_html = REPORT_DIR / f"{job_id}.html"
    log_path = str(LOG_DIR / f"{job_id}.log")

    try:
        _process_xcresult_to_html(
            xcresult_path=job["xcresult_path"],
            out_html_path=str(out_html),
            log_path=log_path,
            report_title=job.get("title", "XCTest Summary"),
            include_details=job.get("include_details", False),
            include_screenshots=False,
            run_by=job.get("run_by") or None,
            run_at=job.get("run_at") or None,
            version=job.get("version") or None,
        )
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["report_path"] = str(out_html)
                _jobs[job_id]["log_path"] = log_path
    except Exception as exc:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(exc)
    finally:
        try:
            shutil.rmtree(str(job_dir), ignore_errors=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# TTL cleanup
# ---------------------------------------------------------------------------

def _ttl_cleanup_loop():
    while True:
        time.sleep(60)
        now = time.time()
        expired = []
        with _jobs_lock:
            for jid, job in list(_jobs.items()):
                if now - job["created_at"] > JOB_TTL_SECONDS:
                    expired.append(jid)
        for jid in expired:
            _do_cleanup(jid)
            print(f"[TTL] Cleaned up expired job {jid}")


def _do_cleanup(job_id: str):
    with _jobs_lock:
        job = _jobs.pop(job_id, None)
    if not job:
        return
    job_dir = UPLOAD_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(str(job_dir), ignore_errors=True)
    for key in ("report_path", "log_path"):
        p = job.get(key)
        if p:
            Path(p).unlink(missing_ok=True)
    json_path = REPORT_DIR / f"{job_id}.json"
    json_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(RequestEntityTooLarge)
def _handle_too_large(exc):
    return jsonify({
        "error": f"Upload too large. Maximum is {MAX_CONTENT_LENGTH // (1024 * 1024)} MB."
    }), 413


@app.errorhandler(400)
def _handle_bad_request(exc):
    return jsonify({"error": "Bad request."}), 400


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/upload", methods=["POST", "OPTIONS"])
@_require_api_key
def api_upload():
    if request.method == "OPTIONS":
        return "", 204

    if _active_job_count() >= MAX_CONCURRENT_JOBS:
        return jsonify({"error": "Server is busy. Please try again in a few minutes."}), 503

    if _dir_size_bytes(_TMP_ROOT) > GLOBAL_DISK_CAP_BYTES:
        return jsonify({"error": "Server disk is near capacity. Try again later."}), 503

    try:
        title = _validate_text_field(
            (request.form.get("title") or "").strip() or "XCTest Summary", "Title"
        )
        include_details = request.form.get("include_details") == "on"
        run_by = _validate_text_field((request.form.get("run_by") or "").strip(), "Who ran it")
        run_at = _validate_text_field((request.form.get("run_at") or "").strip(), "When it ran")
        version = _validate_text_field((request.form.get("version") or "").strip(), "Version")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if "file" not in request.files or not request.files["file"].filename:
        return jsonify({"error": "No file received. Select a .zip containing your .xcresult bundle."}), 400

    job_id = uuid.uuid4().hex[:12]
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        xcresult_path = _unpack_upload(request.files["file"], job_dir)
    except ValueError as exc:
        shutil.rmtree(str(job_dir), ignore_errors=True)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        shutil.rmtree(str(job_dir), ignore_errors=True)
        return jsonify({"error": f"Failed to process upload: {exc}"}), 500

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "processing",
            "created_at": time.time(),
            "xcresult_path": str(xcresult_path),
            "report_path": None,
            "log_path": None,
            "error": None,
            "title": title,
            "include_details": include_details,
            "run_by": run_by,
            "run_at": run_at,
            "version": version,
        }

    threading.Thread(target=_process_job, args=(job_id,), daemon=True).start()

    return jsonify({"job_id": job_id, "status": "processing"}), 202


@app.route("/api/status/<job_id>", methods=["GET", "OPTIONS"])
@_require_api_key
def api_status(job_id):
    if request.method == "OPTIONS":
        return "", 204

    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found or expired."}), 404

    result = {"job_id": job_id, "status": job["status"]}
    if job["status"] == "error":
        result["error"] = job.get("error", "Unknown error")
    return jsonify(result)


@app.route("/api/download/<job_id>", methods=["GET", "OPTIONS"])
@_require_api_key
def api_download(job_id):
    if request.method == "OPTIONS":
        return "", 204

    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found or expired."}), 404
    if job["status"] != "done":
        return jsonify({"error": "Report is not ready yet."}), 409

    report_path = job.get("report_path")
    if not report_path or not Path(report_path).exists():
        return jsonify({"error": "Report file missing."}), 404

    return send_file(
        report_path,
        mimetype="text/html",
        as_attachment=True,
        download_name=f"xctest_report_{job_id}.html",
    )


@app.route("/api/cleanup/<job_id>", methods=["POST", "OPTIONS"])
@_require_api_key
def api_cleanup(job_id):
    if request.method == "OPTIONS":
        return "", 204

    with _jobs_lock:
        if job_id not in _jobs:
            return jsonify({"ok": True, "message": "Already cleaned up."})
    _do_cleanup(job_id)
    return jsonify({"ok": True})


@app.route("/api/health", methods=["GET"])
def api_health():
    with _jobs_lock:
        active = sum(1 for j in _jobs.values() if j["status"] == "processing")
    return jsonify({
        "status": "ok",
        "active_jobs": active,
        "max_concurrent": MAX_CONCURRENT_JOBS,
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="XCResult Report API server (Mac backend)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1; use 0.0.0.0 for external)")
    parser.add_argument("--port", type=int, default=5050,
                        help="Port (default: 5050)")
    parser.add_argument("--debug", action="store_true",
                        help="Flask debug mode")
    parser.add_argument("--api-key", default=None,
                        help="API key for authenticating requests (recommended for production)")
    parser.add_argument("--origins",
                        default="https://www.assurance.st",
                        help="Comma-separated allowed CORS origins (default: https://www.assurance.st)")
    parser.add_argument("--ttl", type=int, default=30,
                        help="Job TTL in minutes before auto-cleanup (default: 30)")
    parser.add_argument("--max-upload-gb", type=float, default=1.0,
                        help="Maximum upload size in GB (default: 1.0)")
    args = parser.parse_args()

    API_KEY = args.api_key
    if API_KEY:
        print(f"API key auth enabled (key length: {len(API_KEY)} chars)")
    else:
        print("WARNING: No API key set. All endpoints are unauthenticated.")

    ALLOWED_ORIGINS = [o.strip() for o in args.origins.split(",") if o.strip()]
    print(f"CORS allowed origins: {ALLOWED_ORIGINS}")

    JOB_TTL_SECONDS = args.ttl * 60
    MAX_CONTENT_LENGTH = int(args.max_upload_gb * 1024 * 1024 * 1024)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    threading.Thread(target=_ttl_cleanup_loop, daemon=True).start()

    print(f"Starting API server on http://{args.host}:{args.port}")
    print(f"Upload limit: {args.max_upload_gb} GB | Job TTL: {args.ttl} min | "
          f"Max concurrent: {MAX_CONCURRENT_JOBS}")
    print(f"Data stored in: {_TMP_ROOT}")

    app.run(host=args.host, port=args.port, debug=args.debug)
