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
from werkzeug.exceptions import RequestEntityTooLarge

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xcresult_gui_v6 import _process_xcresult_to_html  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32).hex()

UPLOAD_DIR = Path(tempfile.gettempdir()) / "xcresult_server_uploads"
REPORT_DIR = Path(tempfile.gettempdir()) / "xcresult_server_reports"
LOG_DIR = Path(tempfile.gettempdir()) / "xcresult_server_logs"

MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2 GB
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


MAX_EXTRACTED_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB total extracted

import re

_SAFE_TEXT_RE = re.compile(r"^[A-Za-z0-9 _.,:;/\-()@#+]+$")
_MAX_FIELD_LEN = 50


def _validate_text_field(value: str, field_name: str) -> str:
    """Validate a user-supplied text field. Returns sanitised value or raises ValueError."""
    value = value.strip()
    if not value:
        return value
    if len(value) > _MAX_FIELD_LEN:
        raise ValueError(f"{field_name} must be {_MAX_FIELD_LEN} characters or fewer.")
    if not _SAFE_TEXT_RE.match(value):
        raise ValueError(f"{field_name} contains invalid characters. Use letters, numbers, spaces, and common punctuation only.")
    return value


def _unpack_upload(file_storage) -> Path:
    """Save an uploaded zip and return the path to the .xcresult inside it.
    Validates against path traversal and zip bombs.
    Deletes the uploaded/extracted files and raises ValueError if the zip is invalid.
    """
    job_id = uuid.uuid4().hex[:12]
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    def cleanup():
        try:
            shutil.rmtree(str(job_dir), ignore_errors=True)
        except Exception:
            pass

    try:
        filename = file_storage.filename or "upload.zip"
        safe_name = Path(filename).name
        saved = job_dir / safe_name
        file_storage.save(str(saved))

        if not zipfile.is_zipfile(str(saved)):
            cleanup()
            raise ValueError(
                "The file is not a valid zip. Upload a .zip that contains a .xcresult bundle."
            )

        extract_dir = job_dir / "extracted"
        extract_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(str(saved), "r") as zf:
            total_size = sum(i.file_size for i in zf.infolist())
            if total_size > MAX_EXTRACTED_SIZE:
                cleanup()
                raise ValueError(
                    f"Zip contents too large ({total_size // (1024*1024)} MB). "
                    f"Limit is {MAX_EXTRACTED_SIZE // (1024*1024)} MB."
                )
            for member in zf.infolist():
                member_path = Path(extract_dir / member.filename).resolve()
                if not str(member_path).startswith(str(extract_dir.resolve())):
                    cleanup()
                    raise ValueError("Zip contains unsafe path entries (path traversal).")
            zf.extractall(str(extract_dir))

        for item in extract_dir.rglob("*.xcresult"):
            if item.is_dir() or item.is_file():
                return item
        if (extract_dir / "Info.plist").exists():
            renamed = extract_dir.with_suffix(".xcresult")
            extract_dir.rename(renamed)
            return renamed
        cleanup()
        raise ValueError(
            "The zip does not contain a valid .xcresult bundle. "
            "Zip the whole folder: right-click the .xcresult in Finder and choose Compress."
        )
    except ValueError:
        raise
    except Exception:
        cleanup()
        raise


def _generate_report(
    xcresult_path: Path,
    title: str,
    include_details: bool,
    cleanup_path=None,
    run_by: str = "",
    run_at: str = "",
    version: str = "",
):
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
            run_by=run_by.strip() or None,
            run_at=run_at.strip() or None,
            version=version.strip() or None,
        )
    except Exception as exc:
        _flash_error(
            f"Error generating report: {exc}",
            "The bundle may be corrupted. \n It might be from an unsupported Xcode version, or not a valid test result.\n Try another .xcresult or re-export from Xcode. \n Try again with the correct file.",
        )
        return redirect(url_for("index"))
    finally:
        if cleanup_path:
            try:
                shutil.rmtree(str(cleanup_path), ignore_errors=True)
            except Exception:
                pass

    return redirect(url_for("report", report_id=report_id))


def _flash_error(msg: str, explanation: str) -> None:
    flash(msg)
    flash(explanation, "explanation")


@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(exc):
    _flash_error(
        "Upload too large. The limit is 2 GB.",
        "The server limits upload size to avoid running out of disk space. Use a smaller .xcresult or zip only the bundle you need.",
    )
    return redirect(url_for("index"))


@app.errorhandler(400)
def handle_bad_request(exc):
    _flash_error(
        "Bad request. The upload may be invalid or empty.",
        "Browsers cannot upload folders. Right-click the .xcresult in Finder and choose Compress, or run: zip -r MyTests.zip MyTests.xcresult",
    )
    return redirect(url_for("index"))


@app.route("/", methods=["GET"])
def index():
    return render_template("upload.html")


@app.route("/upload", methods=["GET"])
def upload_redirect():
    return redirect(url_for("index"))


@app.route("/upload", methods=["POST"])
def upload():
    try:
        title = (request.form.get("title") or "").strip() or "XCTest Summary"
        include_details = request.form.get("include_details") == "on"
        run_by = (request.form.get("run_by") or "").strip()
        run_at = (request.form.get("run_at") or "").strip()
        version = (request.form.get("version") or "").strip()
    except (RequestEntityTooLarge, Exception):
        _flash_error(
            "Upload failed. The request may be too large or malformed.",
            "If you tried to upload a folder, that will not work.<br>"
            "Right-click the .xcresult in Finder and choose <strong>Compress</strong>,<br>"
            "or in Terminal run: <code>zip -r MyTests.zip MyTests.xcresult</code><br>"
            "Then upload the resulting .zip file.",
        )
        return redirect(url_for("index"))

    try:
        title = _validate_text_field(title, "Title") or "XCTest Summary"
        run_by = _validate_text_field(run_by, "Who ran it")
        run_at = _validate_text_field(run_at, "When it ran")
        version = _validate_text_field(version, "Version")
    except ValueError as exc:
        _flash_error(str(exc), "Check the field and remove any unsupported characters.")
        return redirect(url_for("index"))

    has_file = "file" in request.files and request.files["file"].filename

    if not has_file:
        _flash_error(
            "No file received. Select a .zip file containing your .xcresult bundle.",
            "Browsers cannot upload folders.<br>"
            "A .xcresult is a folder that contains the test results.<br>"
            "Right-click it in Finder and choose <strong>Compress</strong> to create a .zip file,<br>"
            "or in Terminal run: <code>zip -r MyTests.zip MyTests.xcresult</code><br>"
            "Then upload the resulting .zip file.",
        )
        return redirect(url_for("index"))

    try:
        xcresult_path = _unpack_upload(request.files["file"])
    except ValueError as exc:
        _flash_error(
            str(exc),
            "The uploaded file was removed. Create the zip by right-clicking the .xcresult in Finder and choosing Compress.",
        )
        return redirect(url_for("index"))
    except Exception as exc:
        _flash_error(
            f"Failed to process upload: {exc}",
            "The uploaded file was removed. Ensure the file is a valid zip containing a .xcresult bundle.",
        )
        return redirect(url_for("index"))

    cleanup = xcresult_path
    while cleanup.parent != UPLOAD_DIR and cleanup.parent != cleanup:
        cleanup = cleanup.parent
    return _generate_report(
        xcresult_path, title, include_details, cleanup_path=cleanup,
        run_by=run_by, run_at=run_at, version=version,
    )


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
    parser.add_argument(
        "--cert",
        metavar="PATH",
        help="Path to TLS certificate (PEM). Enables HTTPS. Use with --key, or a combined PEM for both.",
    )
    parser.add_argument(
        "--key",
        metavar="PATH",
        help="Path to TLS private key (PEM). If omitted with --cert, --cert is used as combined cert+key.",
    )
    args = parser.parse_args()

    ssl_context = None
    if args.cert:
        cert_path = Path(args.cert)
        if not cert_path.exists():
            print(f"Error: certificate file not found: {cert_path}", file=sys.stderr)
            sys.exit(1)
        key_path = Path(args.key).resolve() if args.key else cert_path
        if not key_path.exists():
            print(f"Error: key file not found: {key_path}", file=sys.stderr)
            sys.exit(1)
        ssl_context = (str(cert_path), str(key_path))

    scheme = "https" if ssl_context else "http"
    print(f"Starting XCResult Report server on {scheme}://{args.host}:{args.port}")
    if args.host == "0.0.0.0":
        import socket
        hostname = socket.gethostname()
        try:
            local_ip = socket.gethostbyname(hostname)
        except Exception:
            local_ip = "your-mac-ip"
        print(f"LAN access: {scheme}://{local_ip}:{args.port}")

    app.run(host=args.host, port=args.port, debug=args.debug, ssl_context=ssl_context)
