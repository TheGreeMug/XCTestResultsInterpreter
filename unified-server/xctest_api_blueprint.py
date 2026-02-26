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
  POST /upload        Upload a zip, get back a job_id.
  GET  /status/<id>   Poll job progress.
  GET  /download/<id> Download the finished HTML report.
  POST /cleanup/<id>  Delete all job artefacts.
  GET  /health        Health / readiness check (no auth).

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

from flask import Blueprint, jsonify, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

# Ensure the parent directory of XCTestResultsInterpreter is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from XCTestResultsInterpreter.xcresult_gui_v6 import _process_xcresult_to_html  # noqa: E402

from .shared import add_cors_headers, require_api_key, API_KEY, ALLOWED_ORIGINS

xctest_api_bp = Blueprint('xctest_api_bp', __name__)

_SERVER_DIR = Path(__file__).resolve().parent
_TMP_ROOT = _SERVER_DIR / "tmp_xctest" # Use a distinct temp directory
UPLOAD_DIR = _TMP_ROOT / "uploads"
REPORT_DIR = _TMP_ROOT / "reports"
LOG_DIR = _TMP_ROOT / "logs"

for d in (UPLOAD_DIR, REPORT_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

# MAX_CONTENT_LENGTH = 1 * 1024 * 1024 * 1024  # 1 GB (handled by main app)
MAX_EXTRACTED_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB total uncompressed
MAX_CONCURRENT_JOBS = 2
JOB_TTL_SECONDS = 30 * 60
GLOBAL_DISK_CAP_BYTES = 5 * 1024 * 1024 * 1024

_jobs: dict = {}
_jobs_lock = threading.Lock()

# CORS handled by the main app and shared.py

# Error handlers
@xctest_api_bp.errorhandler(RequestEntityTooLarge)
def _handle_too_large(exc):
    return jsonify({
        "error": f"Upload too large. Maximum is {MAX_CONTENT_LENGTH // (1024 * 1024)} MB."
    }), 413

@xctest_api_bp.errorhandler(400)
def _handle_bad_request(exc):
    return jsonify({"error": "Bad request."}), 400

# Helpers
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

# Zip handling (safe extraction)
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

# Background processing
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

# TTL cleanup
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

# API endpoints
@xctest_api_bp.route("", methods=["GET"])
@xctest_api_bp.route("/", methods=["GET"])
def api_index():
    return jsonify({"service": "xctest", "endpoints": ["/upload", "/status/<id>", "/download/<id>", "/cleanup/<id>", "/health"]})


@xctest_api_bp.route("/upload", methods=["POST", "OPTIONS"])
@require_api_key
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

@xctest_api_bp.route("/status/<job_id>", methods=["GET", "OPTIONS"])
@require_api_key
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

@xctest_api_bp.route("/download/<job_id>", methods=["GET", "OPTIONS"])
@require_api_key
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

@xctest_api_bp.route("/cleanup/<job_id>", methods=["POST", "OPTIONS"])
@require_api_key
def api_cleanup(job_id):
    if request.method == "OPTIONS":
        return "", 204

    with _jobs_lock:
        if job_id not in _jobs:
            return jsonify({"ok": True, "message": "Already cleaned up."})
    _do_cleanup(job_id)
    return jsonify({"ok": True})

@xctest_api_bp.route("/health", methods=["GET"])
def api_health():
    with _jobs_lock:
        active = sum(1 for j in _jobs.values() if j["status"] == "processing")
    return jsonify({
        "status": "ok",
        "active_jobs": active,
        "max_concurrent": MAX_CONCURRENT_JOBS,
    })

# Main execution block removed, handled by main app.py