# XCResult Report -- Web Server

A lightweight Flask server that wraps the existing xcresult processing logic. Point it at a local `.xcresult` path (or upload a zipped bundle from another device) and get back an HTML test report you can view or download.

## Requirements

- macOS with Xcode (or Xcode Command Line Tools) installed
- Python 3.9+

## Setup

All commands assume you are in the **project root** (`XCTestResultsInterpreter/`).

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt        # core project deps
pip install -r server/requirements.txt  # Flask
```

### 3. Start the server

**Localhost only** (same Mac):

```bash
python3 server/app.py
```

The server starts at `http://127.0.0.1:5050`.

**LAN access** (other devices on your network):

```bash
python3 server/app.py --host 0.0.0.0
```

The server prints your local IP so you can open `http://<your-ip>:5050` from another device.

**Custom port:**

```bash
python3 server/app.py --port 8080
```

**HTTPS (secure):**

Use your own TLS certificate and key so the server is served over HTTPS (browsers will show a lock; self-signed certs will show a warning you can accept). Generate a self-signed cert (valid 365 days) in the project or server directory:

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
```

Then start the server with TLS:

```bash
python3 server/app.py --cert cert.pem --key key.pem
```

For LAN access with HTTPS, use the same cert and add `--host 0.0.0.0`. You can use a single combined PEM file for both cert and key: `--cert combined.pem` (omit `--key`).

**"Your connection is not private" / ERR_CERT_AUTHORITY_INVALID:** Browsers show this for self-signed certs because they are not signed by a public CA. This is expected. Choose **Advanced** (or **Show Details**) and then **Proceed to ...** (Chrome) or **Visit this website** (Safari) to continue. You only need to do this once per browser; the connection is still encrypted.

**Debug mode** (auto-reload on code changes):

```bash
python3 server/app.py --debug
```

### 4. Open in browser

Navigate to `http://127.0.0.1:5050` (or your LAN address). If you started with `--cert`/`--key`, use `https://` instead.

## How to use

### Option A: Local path (same Mac -- recommended)

1. Open the server URL in your browser.
2. Paste (or drag from Finder) the full path to your `.xcresult` bundle into the path field, e.g. `/Users/you/test_results/MyTests.xcresult`.
3. Optionally set a report title and enable the detailed test list.
4. Click **Generate Report**.
5. The browser redirects to the generated HTML report.

No zipping needed -- the server reads the `.xcresult` directly from disk.

### Option B: Zip upload (LAN / remote)

Since `.xcresult` bundles are directories, browsers cannot upload them directly. For LAN access from another device:

1. Zip the bundle first:

   ```bash
   zip -r MyTests.zip MyTests.xcresult
   ```

2. Open the server URL and drop the `.zip` onto the upload area.
3. Click **Generate Report**.

### Download the report

After generation, the browser shows the report. To download it:

```
http://127.0.0.1:5050/download/<report_id>
```

## CLI / curl usage

**With a local path:**

```bash
curl -F "local_path=/path/to/MyTests.xcresult" -F "title=Nightly Run" http://127.0.0.1:5050/upload -L -o report.html
```

**With a zip upload:**

```bash
curl -F "file=@MyTests.zip" -F "title=Nightly Run" http://127.0.0.1:5050/upload -L -o report.html
```

The `-L` flag follows the redirect to the generated report.

## Options reference

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address. Use `0.0.0.0` for LAN access. |
| `--port` | `5050` | Port to listen on. |
| `--cert` | - | Path to TLS certificate (PEM). Enables HTTPS. |
| `--key` | - | Path to TLS private key (PEM). Omit if using a combined cert+key file. |
| `--debug` | off | Enable Flask debug mode (auto-reload). |

## File storage

Uploaded bundles are saved to the OS temp directory and cleaned up after processing. Generated reports are kept in the temp directory until the OS clears them or you restart.

## TO DO

Add contact / fill a bug option

## Security notes

- The server is designed for **local / trusted LAN use** with a small number of known users.
- HTTP Basic Auth is enabled by default (username `ETD`, password set via `--password`). Change the default password before first use.
- Use `--cert` and `--key` to serve over **HTTPS** (encrypted). Self-signed certificates are fine for local/LAN; the browser will prompt you to accept the cert once.
- File uploads are capped at 2 GB. Zip contents are checked for path traversal and size before extraction.
- All text fields (title, who ran it, version) are validated: max 50 characters, alphanumeric and common punctuation only.
- **Do not run a generic file server** (e.g. `python -m http.server`) in a directory that contains `.xcresult` bundles. That would expose bundle contents. Use only this application for report generation and serving.

## If you plan to expose this to the public internet

The server was built for trusted LAN use. Before making it internet-facing, you must address the following:

1. **HTTPS is mandatory.** Use `--cert` and `--key` with a proper TLS certificate (e.g. from Let's Encrypt). Without HTTPS, credentials and uploads are sent in plaintext and can be intercepted by anyone on the network path.

2. **Replace HTTP Basic Auth.** Basic Auth sends credentials base64-encoded (not encrypted) on every request. Over HTTPS this is acceptable, but for public use consider replacing it with session-based login (e.g. Flask-Login), OAuth, or an API key header.

3. **Put it behind a reverse proxy.** Do not expose the Flask development server directly. Use a production WSGI server (e.g. gunicorn) behind nginx or Caddy. The reverse proxy handles TLS termination, rate limiting, request buffering, and connection management.

4. **Add rate limiting.** The current server has no rate limiting. An attacker could flood it with uploads to exhaust disk or CPU. Add rate limiting at the reverse proxy level (e.g. nginx `limit_req`) or with Flask-Limiter.

5. **Lower the upload size limit.** 2 GB is generous. For public use, reduce `MAX_CONTENT_LENGTH` to something like 200 MB unless you expect very large bundles.

6. **Add CSRF protection.** The upload form has no CSRF token. An attacker could craft a page that submits a form to your server on behalf of an authenticated user. Use Flask-WTF or add a CSRF token to the form.

7. **Sanitize error messages.** Exception text shown in the help modal may include internal file paths (e.g. `/Users/you/...`). For public use, replace raw exception messages with generic error text and log the details server-side only.

8. **Harden report URLs.** Report IDs are 48-bit random hex strings. For public use, increase to full 128-bit UUIDs or add per-user scoping so users can only access their own reports.

9. **Add log rotation and monitoring.** Logs and reports accumulate in `server/tmp/`. For a public deployment, add log rotation, disk usage monitoring, and more aggressive cleanup (e.g. delete reports after 24 hours instead of 12 months).

10. **Set a strong, persistent secret key.** Set the `SECRET_KEY` environment variable to a fixed random value so session cookies survive server restarts. Generate one with: `python3 -c "import os; print(os.urandom(32).hex())"`.

---

(c) Marius N 2026
