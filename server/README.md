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

**Debug mode** (auto-reload on code changes):

```bash
python3 server/app.py --debug
```

### 4. Open in browser

Navigate to `http://127.0.0.1:5050` (or your LAN address).

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
| `--debug` | off | Enable Flask debug mode (auto-reload). |

## File storage

Uploaded bundles are saved to the OS temp directory and cleaned up after processing. Generated reports are kept in the temp directory until the OS clears them or you restart.

## Security notes

- The server is intended for **local / trusted LAN use only**.
- There is no authentication. Do not expose it to the public internet without adding auth and HTTPS.
- File uploads are capped at 500 MB.

---

(c) Marius N 2026
