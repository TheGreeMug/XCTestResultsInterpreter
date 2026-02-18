#!/usr/bin/env python3
"""
XCResult Report -- Web Server
==============================

Flask app that wraps the existing xcresult processing logic.
Provide a local path to a .xcresult bundle or upload a zipped one,
get back an HTML test report.

Requires macOS with Xcode (or Command Line Tools) for xcresulttool.
"""

import os
import sys
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xcresult_gui_v6 import _process_xcresult_to_html  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "xcresult-dev-key")

UPLOAD_DIR = Path(tempfile.gettempdir()) / "xcresult_server_uploads"
REPORT_DIR = Path(tempfile.gettempdir()) / "xcresult_server_reports"
LOG_DIR = Path(tempfile.gettempdir()) / "xcresult_server_logs"

MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

for d in (UPLOAD_DIR, REPORT_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _cleanup_old_files(directory: Path, max_age_days: int = 365) -> None:
    """Delete files in directory older than max_age_days."""
    import time
    cutoff = time.time() - max_age_days * 86400
    for f in directory.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except Exception:
            pass


_cleanup_old_files(LOG_DIR, max_age_days=365)
_cleanup_old_files(REPORT_DIR, max_age_days=365)


def _resolve_local_path(raw_path: str) -> Path:
    """Validate and return a local .xcresult path."""
    p = Path(raw_path.strip()).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"Path does not exist: {p}")
    if p.suffix != ".xcresult":
        raise ValueError(
            f"Not a .xcresult bundle: {p.name}. "
            "Select a path ending in .xcresult."
        )
    return p


def _unpack_upload(file_storage) -> Path:
    """Save an uploaded zip and return the path to the .xcresult inside it."""
    job_id = uuid.uuid4().hex[:12]
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    filename = file_storage.filename or "upload.zip"
    saved = job_dir / filename
    file_storage.save(str(saved))

    if zipfile.is_zipfile(str(saved)):
        extract_dir = job_dir / "extracted"
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(str(saved), "r") as zf:
            zf.extractall(str(extract_dir))
        for item in extract_dir.rglob("*.xcresult"):
            if item.is_dir() or item.is_file():
                return item
        if (extract_dir / "Info.plist").exists():
            renamed = extract_dir.with_suffix(".xcresult")
            extract_dir.rename(renamed)
            return renamed
        raise ValueError(
            "The zip does not contain a .xcresult bundle. "
            "Zip the .xcresult folder and try again."
        )

    raise ValueError(
        "Unsupported file. Upload a .zip that contains a .xcresult bundle."
    )


def _generate_report(xcresult_path: Path, title: str, include_details: bool, cleanup_path=None):
    """Run the report pipeline and return a redirect to the result, or to index on error."""
    report_id = uuid.uuid4().hex[:12]
    out_html = REPORT_DIR / f"{report_id}.html"
    log_path = str(LOG_DIR / f"{report_id}.log")

    try:
        _process_xcresult_to_html(
            xcresult_path=str(xcresult_path),
            out_html_path=str(out_html),
            log_path=log_path,
            report_title=title,
            include_details=include_details,
            include_screenshots=False,
        )
    except Exception as exc:
        flash(f"Error generating report: {exc}")
        return redirect(url_for("index"))
    finally:
        if cleanup_path:
            try:
                shutil.rmtree(str(cleanup_path), ignore_errors=True)
            except Exception:
                pass

    return redirect(url_for("report", report_id=report_id))


@app.route("/", methods=["GET"])
def index():
    return render_template("upload.html")


@app.route("/upload", methods=["POST"])
def upload():
    title = (request.form.get("title") or "").strip() or "XCTest Summary"
    include_details = request.form.get("include_details") == "on"

    local_path = (request.form.get("local_path") or "").strip()
    has_file = "file" in request.files and request.files["file"].filename

    if not local_path and not has_file:
        flash("Provide a path to a .xcresult bundle or upload a zipped one.")
        return redirect(url_for("index"))

    # Prefer local path if provided
    if local_path:
        try:
            xcresult_path = _resolve_local_path(local_path)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("index"))
        return _generate_report(xcresult_path, title, include_details)

    # Zip upload fallback
    try:
        xcresult_path = _unpack_upload(request.files["file"])
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("index"))
    except Exception as exc:
        flash(f"Failed to process upload: {exc}")
        return redirect(url_for("index"))

    cleanup = xcresult_path
    while cleanup.parent != UPLOAD_DIR and cleanup.parent != cleanup:
        cleanup = cleanup.parent
    return _generate_report(xcresult_path, title, include_details, cleanup_path=cleanup)


@app.route("/report/<report_id>")
def report(report_id):
    html_path = REPORT_DIR / f"{report_id}.html"
    if not html_path.exists():
        flash("Report not found or expired.")
        return redirect(url_for("index"))
    return send_file(str(html_path), mimetype="text/html")


@app.route("/download/<report_id>")
def download(report_id):
    html_path = REPORT_DIR / f"{report_id}.html"
    if not html_path.exists():
        flash("Report not found or expired.")
        return redirect(url_for("index"))
    return send_file(
        str(html_path),
        mimetype="text/html",
        as_attachment=True,
        download_name=f"xctest_report_{report_id}.html",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="XCResult Report web server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (use 0.0.0.0 for LAN access)")
    parser.add_argument("--port", type=int, default=5050, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    print(f"Starting XCResult Report server on http://{args.host}:{args.port}")
    if args.host == "0.0.0.0":
        import socket
        hostname = socket.gethostname()
        try:
            local_ip = socket.gethostbyname(hostname)
        except Exception:
            local_ip = "your-mac-ip"
        print(f"LAN access: http://{local_ip}:{args.port}")

    app.run(host=args.host, port=args.port, debug=args.debug)
