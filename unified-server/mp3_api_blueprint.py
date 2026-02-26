#!/usr/bin/env python3
"""
MP3 Metadata Stripper – API Server (Raspberry Pi / split-deployment backend)
=============================================================================

JSON/file API for the split-deployment architecture:
  - Static frontend (HTML/JS) can live on any host (e.g. cPanel).
  - This API runs on a Raspberry Pi (or any host) behind Caddy (HTTPS),
    receives MP3 uploads, strips metadata with ffmpeg, and returns the file.

Endpoints
---------
  POST /strip   Upload an MP3, get back the stripped file (sync).
  GET  /health  Health check (no auth).

Requires ffmpeg on PATH (e.g. apt install ffmpeg on Raspberry Pi).
"""

import os
import tempfile
from io import BytesIO
from pathlib import Path
from functools import wraps

from flask import Blueprint, request, send_file, jsonify, current_app
from werkzeug.exceptions import RequestEntityTooLarge

# Ensure the strip_mp3 module is accessible
import sys
from .strip_mp3 import strip_mp3

from .shared import add_cors_headers, require_api_key, API_KEY, ALLOWED_ORIGINS

mp3_api_bp = Blueprint('mp3_api_bp', __name__)

# mp3_api_bp.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32).hex() # Handled by main app

ALLOWED_EXTENSIONS = {"mp3"}


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# CORS handled by the main app and shared.py

# Error handlers
@mp3_api_bp.errorhandler(RequestEntityTooLarge)
def _handle_too_large(exc):
    return jsonify({
        "error": f"Upload too large. Maximum is {current_app.config.get('MP3_MAX_CONTENT_LENGTH', 100 * 1024 * 1024) // (1024 * 1024)} MB."
    }), 413


@mp3_api_bp.errorhandler(400)
def _handle_bad_request(exc):
    return jsonify({"error": "Bad request."}), 400


# API endpoints
@mp3_api_bp.route("/strip", methods=["POST", "OPTIONS"])
@require_api_key
def api_strip():
    if request.method == "OPTIONS":
        return "", 204

    if "file" not in request.files or not request.files["file"].filename:
        return jsonify({"error": "No file received. Select an MP3 file."}), 400

    f = request.files["file"]
    if not _allowed_file(f.filename):
        return jsonify({"error": "Only .mp3 files are allowed."}), 400

    try:
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "input.mp3"
            out = Path(tmp) / "output.mp3"
            f.save(str(inp))
            strip_mp3(inp, out)
            data = out.read_bytes()
        return send_file(
            BytesIO(data),
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=Path(f.filename).stem + "_stripped.mp3",
        )
    except FileNotFoundError as e:
        if "ffmpeg" in str(e).lower():
            return jsonify({"error": "Server error: ffmpeg is not installed or not on PATH."}), 503
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Processing failed: {e}"}), 500


@mp3_api_bp.route("/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok"})


# Main execution block removed, handled by main app.py