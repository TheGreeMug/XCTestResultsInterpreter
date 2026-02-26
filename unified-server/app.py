import os
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request

from .xctest_api_blueprint import xctest_api_bp, _ttl_cleanup_loop, _TMP_ROOT as XCTEST_TMP_ROOT, GLOBAL_DISK_CAP_BYTES, MAX_CONCURRENT_JOBS, _jobs, _jobs_lock
from .mp3_api_blueprint import mp3_api_bp
from . import shared
from .shared import add_cors_headers

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32).hex()

# Register blueprints
app.register_blueprint(xctest_api_bp, url_prefix='/xctest/api')
app.register_blueprint(mp3_api_bp, url_prefix='/mp3/api')

@app.after_request
def cors_headers(response):
    return add_cors_headers(response)

@app.route("/", methods=["GET"])
def root():
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>API</title></head><body>"
        "<p>Unified API server (XCTest reports + MP3 strip).</p>"
        "<p>Use the frontends; this host is for API calls only.</p>"
        "<p><a href='/health'>/health</a></p></body></html>"
    ), 200, {"Content-Type": "text/html; charset=utf-8"}


# Health check for the unified server
@app.route("/health", methods=["GET"])
def health_check():
    # You can extend this to check the health of both sub-services if needed
    # For now, it just indicates the main app is running.
    with _jobs_lock:
        active_xctest_jobs = sum(1 for j in _jobs.values() if j["status"] == "processing")
    return jsonify({
        "status": "ok",
        "xctest_active_jobs": active_xctest_jobs,
        "xctest_max_concurrent": MAX_CONCURRENT_JOBS,
    })


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Unified API server for XCTest Reports and MP3 Stripping")
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
    parser.add_argument("--xctest-ttl", type=int, default=30,
                        help="XCTest Job TTL in minutes before auto-cleanup (default: 30)")
    parser.add_argument("--xctest-max-upload-gb", type=float, default=1.0,
                        help="XCTest Maximum upload size in GB (default: 1.0)")
    parser.add_argument("--mp3-max-upload-mb", type=int, default=100,
                        help="MP3 Maximum upload size in MB (default: 100)")
    args = parser.parse_args()

    # Patch shared module so blueprints see API key and CORS origins
    shared.API_KEY = args.api_key
    shared.ALLOWED_ORIGINS = [o.strip() for o in args.origins.split(",") if o.strip()]
    if shared.API_KEY:
        print(f"API key auth enabled (key length: {len(shared.API_KEY)} chars)")
    else:
        print("WARNING: No API key set. All endpoints are unauthenticated.")
    print(f"CORS allowed origins: {shared.ALLOWED_ORIGINS}")

    # Config lives on the app; blueprints read via current_app.config
    app.config["XCTEST_MAX_CONTENT_LENGTH"] = int(args.xctest_max_upload_gb * 1024 * 1024 * 1024)
    app.config["MP3_MAX_CONTENT_LENGTH"] = args.mp3_max_upload_mb * 1024 * 1024
    app.config["MAX_CONTENT_LENGTH"] = max(app.config["XCTEST_MAX_CONTENT_LENGTH"], app.config["MP3_MAX_CONTENT_LENGTH"])

    threading.Thread(target=_ttl_cleanup_loop, daemon=True).start()

    print(f"Starting unified API server on http://{args.host}:{args.port}")
    print(f"XCTest Upload limit: {args.xctest_max_upload_gb} GB | XCTest Job TTL: {args.xctest_ttl} min | "
          f"XCTest Max concurrent: {MAX_CONCURRENT_JOBS}")
    print(f"MP3 Upload limit: {args.mp3_max_upload_mb} MB")
    print(f"XCTest data stored in: {XCTEST_TMP_ROOT}")

    app.run(host=args.host, port=args.port, debug=args.debug)