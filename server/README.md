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

## Security notes

- The server is intended for **local / trusted LAN use only**.
- Use `--cert` and `--key` to serve over **HTTPS** (encrypted). Self-signed certificates are fine for local/LAN; the browser will prompt you to accept the cert once.
- There is no authentication. Do not expose the server to the public internet without adding auth (and HTTPS).
- File uploads are capped at 2 GB.

---

(c) Marius N 2026
