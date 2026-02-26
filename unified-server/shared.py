import os
from functools import wraps
from flask import request, jsonify

API_KEY = None
ALLOWED_ORIGINS: list[str] = []

def add_cors_headers(response):
    origin = request.headers.get("Origin", "")
    if origin and (origin in ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "3600"
        response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
    return response

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "OPTIONS":
            return f(*args, **kwargs)
        if API_KEY is None:
            return f(*args, **kwargs)
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated
