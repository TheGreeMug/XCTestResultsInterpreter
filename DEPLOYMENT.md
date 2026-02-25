# XCResult Report – Mac Backend + Hosted Frontend

This document explains how to start and configure the **Mac backend API** (with Caddy) and the **hosted static frontend** (e.g. on cPanel) for the split-deployment setup.

The flow:

1. A static HTML/JS frontend runs on a regular web host (e.g. `https://assurance.st`).
2. The frontend sends uploads to a Mac API endpoint (e.g. `https://astudvpn.asuscomm.com`).
3. The Mac processes the `.xcresult.zip` using Xcode tools and returns an HTML report for download.

---

## 1. Requirements

- A Mac running:
  - macOS with **Xcode** or **Xcode Command Line Tools** (for `xcresulttool`).
  - **Python 3.9+**.
  - **Caddy** (reverse proxy / TLS termination).
- A DNS name pointing to your Mac (e.g. `astudvpn.asuscomm.com`).
- A static hosting account (e.g. cPanel) for serving `frontend/index.html` over HTTPS.

> All shell commands assume you are in the project root: `XCTestResultsInterpreter/`.

---

## 2. Mac backend API (Flask) setup

### 2.1 Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r server/requirements.txt
```

### 2.2 Generate an API key

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy this value; you will use it:

- When starting `server/api.py` on the Mac.
- In the `API_KEY` constant in `frontend/index.html` on your hosting.

### 2.3 Start the API server

Example (adjust origins and API key to your domains):

```bash
source .venv/bin/activate
python3 server/api.py \
  --host 127.0.0.1 \
  --port 5050 \
  --api-key "YOUR_API_KEY_HERE" \
  --origins "https://assurance.st,https://www.assurance.st"
```

Notes:

- `--host 127.0.0.1` binds only to localhost; external traffic will arrive via Caddy.
- `--origins` is a comma-separated list of **exact origins** that are allowed to call the API (CORS). Make sure it matches the real frontend origin (`https://assurance.st` vs `https://www.assurance.st`).
- `--max-upload-gb` and `--ttl` can be tuned if needed.

You can quickly check that the API is healthy from the Mac:

```bash
curl http://127.0.0.1:5050/api/health
```

You should see JSON like:

```json
{"status":"ok","active_jobs":0,"max_concurrent":2}
```

Keep this terminal running while you use the system.

---

## 3. Caddy reverse proxy (HTTPS on the Mac)

### 3.1 Install Caddy

On the Mac:

```bash
brew install caddy
```

### 3.2 Configure Caddyfile

In the project root there is a `Caddyfile` similar to:

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

astudvpn.asuscomm.com {
  request_body {
    max_size 1100MB
  }

  reverse_proxy localhost:5050
}
```

Update the site name (`astudvpn.asuscomm.com`) to match your DNS name if needed.

### 3.3 Router port forwarding

On your router, forward:

- **TCP 80 → your Mac’s local IP** (for Let’s Encrypt HTTP challenge).
- **TCP 443 → your Mac’s local IP** (HTTPS traffic).

Make sure your public DNS record for the chosen hostname points to your public IP.

### 3.4 Start Caddy

From the project root:

```bash
sudo caddy start
```

Caddy will:

- Obtain a TLS certificate from Let’s Encrypt for your domain.
- Terminate HTTPS on ports 80/443.
- Proxy `/api/...` requests to `http://127.0.0.1:5050`.

You can verify from any machine on the internet:

```bash
curl https://your-domain.example.com/api/health
```

You should see the same JSON as the local health check.

---

## 4. Frontend (static hosting, e.g. cPanel)

### 4.1 Files to upload

From the project root, the frontend lives in `frontend/`. Upload at least:

- `frontend/index.html`
- `server/static/xctest_result.png` (favicon/logo)
- `server/static/UploadTestBundleCompressed.gif` (how-to animation)

Place these in your hosting’s document root, for example:

- `public_html/index.html`
- `public_html/xctest_result.png`
- `public_html/UploadTestBundleCompressed.gif`

Or under a subfolder (e.g. `public_html/xcresult/`), as long as all three files stay together.

### 4.2 Configure API URL and API key in the frontend

Edit `frontend/index.html` (either locally before upload or via your hosting’s file editor) and set:

```js
// CONFIGURATION -- update these two values before deploying
var API_URL = 'https://your-domain.example.com';   // Mac backend (Caddy -> Flask)
var API_KEY = 'YOUR_API_KEY_HERE';                 // same value as --api-key
```

Use the same API key you passed to `server/api.py`.

Re-upload the updated `index.html` to your hosting.

To confirm the changes are live:

1. Open your site in a browser (e.g. `https://assurance.st`).
2. View page source and search for `var API_URL`.
3. Check that it shows the correct `https://...` URL and non-empty API key.

### 4.3 Test end-to-end

1. On the Mac, ensure:
   - `server/api.py` is running.
   - Caddy is running and has a valid certificate.
2. In a browser, open your hosted frontend (e.g. `https://assurance.st`).
3. Upload a small `.xcresult.zip`.

You should see:

- Upload progress bar and “Uploading…” message.
- “Converting… please wait.” while the Mac processes the bundle.
- Automatic download of the HTML report when done.
- A success banner with a “Download again” link.

If the frontend ever shows **“Connection failed / Could not reach the conversion server”**, check:

1. `API_URL` in `index.html` matches the real HTTPS URL (including `https://` and the correct hostname).
2. The API is reachable from that browser:
   - Open `https://your-domain.example.com/api/health` and verify it returns JSON.
3. `--origins` passed to `server/api.py` includes the exact origin of your frontend (for example, `https://assurance.st` vs `https://www.assurance.st`).

---

## 5. Operational notes

- **Uploads and reports** are stored under `server/tmp/` on the Mac and auto-cleaned after a TTL (default 30 minutes).
- **Global disk cap** is enforced (default 5 GB) to avoid filling the disk with jobs.
- At most **2 concurrent jobs** are processed by default; additional uploads receive a “Server is busy” error until a slot frees up.
- For production-like usage, consider running the API behind a production WSGI server (e.g. gunicorn) instead of Flask’s development server.

---

© Marius N 2026

