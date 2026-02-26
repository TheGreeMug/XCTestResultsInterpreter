# Unified API Server (XCResult + MP3 Strip)

Single Flask application that serves both:

1. **XCResult Report API** – upload a `.xcresult.zip`, get an HTML test report (async: upload, poll status, download).
2. **MP3 Metadata Stripper API** – upload an MP3, get back the same file with metadata stripped (sync).

Both APIs share one process, one port, and the same API key and CORS configuration. Designed to run behind Caddy (or another reverse proxy) for HTTPS.

---

## Requirements

- **macOS** – XCResult processing requires Xcode or Xcode Command Line Tools (`xcresulttool`).
- **Python 3.9+**
- **ffmpeg** – for MP3 stripping (`brew install ffmpeg`).
- **Caddy** (optional) – for TLS and reverse proxy in front of the Flask app.

The unified server lives inside the **XCTestResultsInterpreter** project. The XCResult blueprint imports `xcresult_gui_v6` from that parent project. The MP3 logic is self-contained in this folder (including `strip_mp3.py`).

---

## Project layout

```
unified-server/
  app.py                  # Main Flask app; registers blueprints, sets config, runs server
  shared.py               # CORS headers and API-key auth (used by both blueprints)
  xctest_api_blueprint.py # XCResult: /xctest/api/upload, /status/<id>, /download/<id>, /cleanup/<id>, /health
  mp3_api_blueprint.py    # MP3: /mp3/api/strip, /health
  strip_mp3.py            # MP3 stripping logic (ffmpeg)
  requirements.txt
  Caddyfile               # Example Caddy config for HTTPS and path-based routing
  tmp_xctest/             # Created at runtime: XCResult uploads/reports/logs (auto-cleaned by TTL)
```

---

## Setup

From the **parent directory** of `unified-server` (the XCTestResultsInterpreter repo root):

```bash
cd path/to/XCTestResultsInterpreter

python3 -m venv unified-server/.venv
source unified-server/.venv/bin/activate   # or: . unified-server/.venv/bin/activate
pip install -r unified-server/requirements.txt
```

Install ffmpeg if needed:

```bash
brew install ffmpeg
```

---

## Running the server

Run from the **parent directory** (so `unified-server` is a proper package). Do not run from inside `unified-server/`.

```bash
cd path/to/XCTestResultsInterpreter

source unified-server/.venv/bin/activate
python3 -m unified-server.app \
  --host 127.0.0.1 \
  --port 5050 \
  --api-key "YOUR_API_KEY" \
  --origins "https://assurance.st,https://www.assurance.st" \
  --xctest-max-upload-gb 1.0 \
  --xctest-ttl 30 \
  --mp3-max-upload-mb 100
```

- **--host** – Bind address. Use `127.0.0.1` when Caddy (or another proxy) is in front.
- **--port** – Default 5050.
- **--api-key** – Required for authenticated access to `/xctest/api/*` and `/mp3/api/*` (except health). Omit to allow unauthenticated access (not recommended for production).
- **--origins** – Comma-separated CORS origins. Must match the exact origin(s) of your frontend (e.g. with or without `www`).
- **--xctest-ttl** – Minutes before XCResult job artefacts are removed (default 30).
- **--xctest-max-upload-gb** – Max upload size for XCResult (default 1.0).
- **--mp3-max-upload-mb** – Max upload size for MP3 in MB (default 100).

Quick health check (local):

```bash
curl http://127.0.0.1:5050/health
curl http://127.0.0.1:5050/xctest/api/health
curl http://127.0.0.1:5050/mp3/api/health
```

---

## API endpoints

| Path | Method | Description |
|------|--------|-------------|
| `/` | GET | Simple landing page (API info). |
| `/health` | GET | Unified health (no auth). |
| `/xctest/api` | GET | XCResult API description (no auth). |
| `/xctest/api/upload` | POST | Upload .xcresult.zip; returns `job_id` (auth). |
| `/xctest/api/status/<job_id>` | GET | Poll job status (auth). |
| `/xctest/api/download/<job_id>` | GET | Download report (auth). |
| `/xctest/api/cleanup/<job_id>` | POST | Delete job artefacts (auth). |
| `/xctest/api/health` | GET | XCResult health (no auth). |
| `/mp3/api/strip` | POST | Upload MP3; response is stripped file (auth). |
| `/mp3/api/health` | GET | MP3 health (no auth). |

Auth: send the same value as `--api-key` in the `X-API-Key` header (or `api_key` query param). Health endpoints do not require auth.

---

## Frontend configuration

Static frontends (e.g. on cPanel) call the API by combining `API_URL` with a path. The server expects **no double `/api`** in the path.

- **XCResult frontend** (e.g. `xcoderesults.html`):  
  `API_URL = 'https://your-domain.com/xctest'`  
  The frontend then uses `API_URL + '/api/upload'`, which becomes `https://your-domain.com/xctest/api/upload`.

- **MP3 frontend** (e.g. `mp3-strip.html`):  
  `API_URL = 'https://your-domain.com/mp3'`  
  The frontend uses `API_URL + '/api/strip'` → `https://your-domain.com/mp3/api/strip`.

Use the same `API_KEY` in both frontends as passed to `--api-key`. Add your frontend origin(s) to `--origins`.

---

## Caddy (HTTPS)

Example Caddyfile in this directory. Replace the domain with yours and run Caddy from this directory:

```caddyfile
{
  servers {
    timeouts {
      read_body   10m
      read_header 30s
      write       10m
      idle        5m
    }
  }
}

your-domain.com {
  request_body {
    max_size 1100MB
  }

  handle /xctest/api/* {
    reverse_proxy 127.0.0.1:5050
  }

  handle /mp3/api/* {
    reverse_proxy 127.0.0.1:5050
  }

  handle {
    reverse_proxy 127.0.0.1:5050
  }
}
```

Then:

```bash
cd unified-server
sudo caddy run --config ./Caddyfile
```

Ensure the Flask app is running on `127.0.0.1:5050`. Forward ports 80 and 443 to this machine and point DNS at it so Caddy can obtain a certificate.

---

## Operational notes

- **No persistent storage** – Uploaded files and reports are temporary. XCResult jobs are removed after the TTL; MP3 is processed in memory/temp and the response is returned. Aligns with a “we don’t store your data” / GDPR-friendly posture.
- **XCResult limits** – Configurable max concurrent jobs, disk cap, and per-upload size; see the XCResult blueprint and `app.py` for defaults.
- **Single process** – Both services run in one Flask process. For production, consider running the app with a production WSGI server (e.g. gunicorn) behind Caddy instead of the built-in dev server.

---

## Troubleshooting

- **ImportError / “no known parent package”** – Run `python3 -m unified-server.app` from the **parent** of `unified-server` (XCTestResultsInterpreter root), not from inside `unified-server`.
- **404 on `/xctest/api/api/upload`** – Frontend is using `API_URL` with a trailing `/api`. Use `API_URL = '.../xctest'` (no trailing `/api`).
- **CORS errors** – Ensure `--origins` includes the exact origin of the page (e.g. `https://assurance.st` vs `https://www.assurance.st`).
- **MP3 “ffmpeg not found”** – Install ffmpeg and ensure it is on the server’s PATH.
