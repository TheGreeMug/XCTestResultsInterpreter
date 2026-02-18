# XCTestResultsInterpreter

Python GUI and CLI for turning Xcode `.xcresult` bundles into HTML test reports. Extracts passed/failed/skipped counts via `xcrun xcresulttool`, renders a summary with a Chart.js pie chart, and optionally exports to PDF. macOS only; can be packaged as a standalone app.

## Table of contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
  - [GUI mode](#gui-mode)
  - [CLI mode](#cli-mode)
  - [Web server](#web-server)
- [Dependencies](#dependencies)
- [Distributing to another Mac](#distributing-to-another-mac)
- [Notes](#notes)

## Features

- Extracts test counts (passed, failed, skipped) from `.xcresult` bundles using `xcrun xcresulttool`
- Generates an HTML summary page with a Chart.js pie chart (dark theme by default; light/dark toggle in report)
- Optional PDF export via WeasyPrint
- Tkinter-based GUI with optional drag-and-drop via `tkinterdnd2`
- Web server mode: upload `.xcresult` bundles from any browser on your Mac or LAN
- Print-friendly: report uses readable text and light background when printing

## Prerequisites

- macOS with Xcode installed (the script uses `xcresulttool` via `xcrun`)
- Python 3.9 or newer

## Installation

1. Clone or download this repository, then open a terminal in the project folder.

2. Create and activate a virtual environment (recommended):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Ensure Xcode (or Xcode Command Line Tools) is installed and selected, e.g.:

   ```bash
   xcode-select --install
   xcode-select --switch /Applications/Xcode.app/Contents/Developer
   ```

## Usage

### GUI mode

Run the Tkinter GUI (default):

```bash
python3 xcresult_gui_v6.py
```

Steps:

1. Drag and drop a `.xcresult` bundle into the drop area, or click **Browse...** to select it.
2. Set the HTML output path (or keep the default).
3. Optionally set the log file path and report title.
4. Optionally enable **Include detailed test list** for failure details in the report.
5. Click **Generate HTML** to create the report.
6. Open the generated HTML in a browser. Use the theme toggle in the report to switch between dark and light. Use the browser’s Print (or Print to PDF) when needed; the report switches to a light background and dark text for printing.

### CLI mode

For CI or scripts, run without GUI:

```bash
python3 xcresult_gui_v6.py --cli /path/to/Tests.xcresult --output-html /path/to/report.html
```

Options:

| Option | Description |
|--------|-------------|
| `--cli` | Run in CLI mode (no GUI). |
| positional | Path to the `.xcresult` bundle. |
| `--output-html` | Path for the HTML report (required in CLI). |
| `--log-path` | Optional log file path. If omitted, a timestamped log is created in the project directory. |
| `--pdf-output` | Optional path for a PDF (requires WeasyPrint). |
| `--title` | Optional report title. |
| `--include-details` | Include detailed test list in the report. |
| `--include-screenshots` | Include screenshots (only with `--include-details`). |

Exit codes: `0` on success, non-zero on error.

### Web server

A Flask-based web server lets you upload zipped `.xcresult` bundles from any browser (same Mac or LAN). Install the extra dependency and start the server:

```bash
pip install -r server/requirements.txt
python3 server/app.py
```

Then open `http://127.0.0.1:5050` in your browser. For LAN access use `--host 0.0.0.0`. See [`server/README.md`](server/README.md) for full setup and usage details.

## Dependencies

- **tkinter** -- included with Python on macOS (used for the GUI).
- **tkinterdnd2** -- optional; enables drag-and-drop in the GUI. Install with `pip install tkinterdnd2`.
- **weasyprint** -- optional; enables PDF export from HTML. Install with `pip install weasyprint` (may require extra system libraries).
- **flask** -- required only for the web server (`pip install -r server/requirements.txt`).

## Distributing to another Mac

**Option A: Share the project**

Zip the project and send it. On the other Mac they need Python 3 and Xcode (or Command Line Tools). Then:

```bash
cd XCTestResultsInterpreter
pip install -r requirements.txt
python3 xcresult_gui_v6.py
```

**Option B: Standalone app (no Python on the other Mac)**

Build a double-clickable macOS app. The other Mac still needs Xcode (or Command Line Tools) for `xcresulttool`.

1. In the project folder, run:

   ```bash
   pip install -r requirements-build.txt
   chmod +x build_app.sh
   ./build_app.sh
   ```

   Use the same Python you will run with (e.g. `pip3.12 install -r requirements-build.txt` if you use Python 3.12).

2. In `dist/` you get **XCResult Report.app**. Copy the whole `.app` (or zip it) to the other Mac.

3. On the other Mac, double-click the app. If macOS blocks it, right-click the app and choose **Open** once.

**Bundled or nearby xcresult:** If you have a file or folder named `xcresults` in the project when you run `./build_app.sh`, it is packed into the app and pre-selected at launch. You can also place `xcresults` next to the app on the target Mac and the app will detect it.

**App icon:** Put `icon.icns` (or `XCResult Report.icns` / `app.icns`) in the project folder and run `./build_app.sh` again to use a custom icon.

PDF export (WeasyPrint) may not work inside the standalone app if system libraries are missing; HTML generation does not depend on it.

## Notes

- A JSON copy of the extracted summary is written next to the HTML (same basename, `.json` extension) for debugging.
- Logs are plain text and useful for troubleshooting `xcresulttool` or path issues.

---

© Marius N 2026
