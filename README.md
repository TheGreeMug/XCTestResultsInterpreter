# XCTestResultsInterpreter
Python GUI and CLI for turning Xcode `.xcresult` bundles into HTML test reports. Extracts passed/failed/skipped counts via `xcrun xcresulttool`, renders a summary with a Chart.js pie chart, and optionally exports to PDF. Use the Tkinter GUI (with drag-and-drop) or run from the command line for CI. macOS only; can be packaged as a standalone app.
XCTestResultsInterpreter
========================

**Description**

Python GUI and CLI for turning Xcode `.xcresult` bundles into HTML test reports. Extracts passed/failed/skipped counts via `xcrun xcresulttool`, renders a summary with a Chart.js pie chart, and optionally exports to PDF. Use the Tkinter GUI (with drag-and-drop) or run from the command line for CI. macOS only; can be packaged as a standalone app.

Features
--------

- Extracts test counts (passed, failed, skipped) from `.xcresult` bundles using `xcrun xcresulttool`.
- Generates a clean HTML summary page with a Chart.js pie chart.
- Optional PDF export via WeasyPrint.
- Tkinter-based GUI with optional drag-and-drop support via `tkinterdnd2`.

Prerequisites
-------------

- macOS with Xcode installed (the script calls `xcresulttool` via `xcrun`).
- Python 3.9 or newer is recommended.

Installation
------------

1. Create and activate a virtual environment (recommended).
2. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Ensure Xcode is installed and selected (for example, via `xcode-select --install` and `xcode-select --switch` if needed).

Usage
-----

### GUI mode

The default behavior is to run the Tkinter GUI:

```bash
python3 xcresult_gui_v6.py
```

Steps in the GUI:

1. Drag and drop your `.xcresult` bundle into the drop area, or click "Browse…" to select it.
2. Choose an HTML output path.
3. Optionally adjust the log file path.
4. Click "Generate HTML" to create the report.
5. Optionally click "Export PDF" (requires WeasyPrint) to create a PDF from the generated HTML.

### CLI mode

You can also run the tool non-interactively from the command line. This is useful for CI or scripted workflows.

Basic example:

```bash
python3 xcresult_gui_v6.py --cli /path/to/Tests.xcresult --output-html /path/to/report.html
```

Options:

- `--cli`: Run in CLI mode instead of opening the GUI.
- Positional argument: the `.xcresult` bundle path.
- `--output-html`: Path where the HTML report should be written.
- `--log-path`: Optional path to a log file. If omitted, a timestamped log file is created in your home directory.
- `--pdf-output`: Optional path for a PDF file. If provided, WeasyPrint is used to convert the generated HTML to PDF.

Exit codes:

- `0` on success.
- Non-zero if the `.xcresult` bundle cannot be processed or files cannot be written.

Dependencies
------------

Core Python dependencies are listed in `requirements.txt`:

- `tkinterdnd2` (optional; enables drag-and-drop in the GUI).
- `weasyprint` (optional; enables PDF export from HTML).

Tkinter itself is part of the Python standard library on macOS, but you may need to ensure your Python installation includes it.

Distributing to another Mac
----------------------------

**Option A: Share the project**

Zip the project folder and send it. On the other Mac they need Python 3 and Xcode (or Command Line Tools). Then:

```bash
cd XCTestResultsInterpreter
pip install -r requirements.txt
python3 xcresult_gui_v6.py
```

**Option B: Build a standalone app (no Python required on the other Mac)**

You can turn the script into a double-clickable macOS app so the other person does not need Python installed. They still need **Xcode** (or `xcresulttool` via Xcode Command Line Tools) for the tool to work.

1. On your Mac, open a terminal in the **project folder** (the one that contains `build_app.sh` and `xcresult_gui_v6.py`). Then run:

   ```bash
   pip install -r requirements-build.txt
   chmod +x build_app.sh
   ./build_app.sh
   ```

   (If you are in the parent folder, run `cd XCTestResultsInterpreter` first.)  
   If you have multiple Python versions, install with the one you will use to run the script (e.g. `pip3.12 install -r requirements-build.txt`). The build script tries `python3.12`, `python3.11`, then `python3` and uses the first that has PyInstaller.

2. In the `dist/` folder you will get **XCResult Report.app**. Copy that entire `.app` (or zip it) and send it to the other Mac.

3. On the other Mac they can put the app in Applications or anywhere, then double-click it. The first time, they may need to right-click the app and choose "Open" if macOS blocks it (Gatekeeper). Default report output and logs will be created in the same folder as the app.

**Bundled or nearby xcresults:** If you have a file (or folder) named `xcresults` in the project when you run `./build_app.sh`, it will be packed into the app and pre-selected when the app opens. If you do not pack it, you can still place a file or folder named `xcresults` in the same folder as the app on the other Mac; the app will detect it and pre-fill the input path (no install needed).

**App icon:** To give the built app a custom icon, add a macOS icon file named `icon.icns` (or `XCResult Report.icns` or `app.icns`) in the project folder and run `./build_app.sh` again. The script will use it automatically. To create an `.icns` from a PNG: create a folder `icon.iconset`, add your PNG at the required sizes (e.g. 16, 32, 128, 256, 512 px), then run `iconutil -c icns icon.iconset` on macOS.

Note: PDF export (WeasyPrint) depends on system libraries; it may not work inside the standalone app unless those are installed on the target Mac. HTML report generation works without it.

Notes
-----

- The tool writes a copy of the extracted JSON summary next to the generated HTML file (same basename, `.json` extension) to help debug unexpected counts.
- Logs are written to a plain text file for troubleshooting external tool issues (for example, `xcresulttool` failures due to Xcode configuration).

© Marius N 2026
