#!/usr/bin/env python3
"""
xcresult_gui.py
================

A small Tk-based utility that helps extract a minimal summary from a `.xcresult`
test bundle and render it to an HTML report.  The tool aims to be friendly
for beginners: it provides a drag-and-drop area for dropping the result
bundle, a button to choose where to save the generated HTML, and a button to
perform the conversion.  Optionally, if `weasyprint` is installed, the
generated HTML can be converted to a PDF directly from the GUI.

This script assumes it is run on macOS with Xcode installed, because it
invokes the `xcresulttool` command via `xcrun` to extract a JSON summary from
the `.xcresult` bundle.  See the man page for `xcresulttool` for details on
the commands used; the summary is obtained with
`xcresulttool get test-results summary --path <bundle>`, which returns a
machine-readable summary of test results【52938855005681†L11-L18】.  If your
Xcode installation doesn't support the `test-results summary` subcommand,
the script falls back to the more generic `get --path ... --format json`.

Drag-and-drop support is provided by the third-party `tkinterdnd2` module.
You can install it with `pip install tkinterdnd2`.  A simple example of
registering a widget as a file drop target looks like this【548805974107881†L96-L116】.
The script uses the same approach: a frame on the left advertises itself as
a drop target for files of type `DND_FILES` and the handler stores the first
dropped path in a variable.

To convert HTML into a PDF automatically, the script tries to import
`weasyprint`.  According to recent guidance on HTML-to-PDF tools,
WeasyPrint can be installed with `pip install weasyprint` and then used
like `from weasyprint import HTML; HTML(string=html).write_pdf(out_path)`
【330858033193399†L485-L516】.  If `weasyprint` is unavailable, the PDF button
is disabled and the user can manually print the HTML via their browser.

Usage (GUI):
    python3 xcresult_gui_v6.py

This will open a window.  Drag your `.xcresult` bundle into the drop area,
choose an output HTML file, then click “Generate HTML”.  After generation,
you can optionally click “Export PDF” if WeasyPrint is installed.

Usage (CLI):
    python3 xcresult_gui_v6.py --cli /path/to/Tests.xcresult --output-html /path/to/report.html

In CLI mode, the tool processes the `.xcresult` bundle non-interactively,
writes the HTML report to the given path, and exits with a non-zero status
code if an error occurs.

"""

# © Marius N 2026

import argparse
import json
import datetime
import os
import random
import subprocess
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_WEASY_AVAILABLE = False  # Lazy-import WeasyPrint in _export_pdf to avoid noisy import warnings

try:
    # Import TkinterDnD2 for drag-and-drop support.  The import structure is
    # slightly unusual: the TkinterDnD module exposes a class named `Tk` that
    # is used in place of `tk.Tk()`【548805974107881†L96-L116】.
    from tkinterdnd2 import TkinterDnD, DND_FILES  # type: ignore

    _DND_AVAILABLE = True
except Exception:
    _DND_AVAILABLE = False

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# --- Simple file logging (for debugging) ---
def _script_dir() -> Path:
    """Directory for default output and logs. When run as a frozen app (.app), use the folder containing the app (one level above the .app)."""
    if getattr(sys, "frozen", False):
        # PyInstaller: executable is inside .app/Contents/MacOS/; app bundle is parent.parent.parent; one more parent = folder containing the .app
        return Path(sys.executable).resolve().parent.parent.parent.parent
    try:
        return Path(__file__).resolve().parent
    except Exception:
        return Path.cwd()


def _default_output_dir() -> Path:
    """Script's path / output; created if missing."""
    out = _script_dir() / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _default_output_path() -> str:
    """Default HTML report path: script_dir/output/report.html."""
    return str(_default_output_dir() / "report.html")


def _next_available_report_path(path: str) -> str:
    """If path exists, return next available path: report_1.html, report_2.html, ..."""
    p = Path(path)
    if not p.exists():
        return path
    parent = p.parent
    stem = p.stem
    suffix = p.suffix or ".html"
    n = 1
    while (parent / f"{stem}_{n}{suffix}").exists():
        n += 1
    return str(parent / f"{stem}_{n}{suffix}")


def _default_log_path() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return str(_script_dir() / f"xcresult_gui_{ts}.log")


def _default_xcresult_path() -> Optional[str]:
    """Path to a bundled or nearby 'xcresults' file for pre-fill, or None."""
    if getattr(sys, "frozen", False):
        # Packed inside the app (PyInstaller)
        try:
            meipass = Path(sys._MEIPASS)
            bundled = meipass / "xcresults"
            if bundled.exists():
                return str(bundled)
        except Exception:
            pass
        # Next to the app (no install: user put xcresults beside the .app)
        next_to_app = _script_dir() / "xcresults"
        if next_to_app.exists():
            return str(next_to_app)
    else:
        # Running as script: same folder as script
        same_dir = _script_dir() / "xcresults"
        if same_dir.exists():
            return str(same_dir)
    return None

def _log(log_path: str, msg: str) -> None:
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        pass


def _process_xcresult_to_html(
    xcresult_path: str,
    out_html_path: str,
    log_path: str,
    report_title: Optional[str] = None,
    include_details: bool = False,
    include_screenshots: bool = False,
) -> Tuple[int, int, int]:
    """Shared helper to run xcresulttool, extract counts, and write HTML+JSON.

    Returns a tuple of (passed, failed, skipped). Raises on unrecoverable
    I/O or JSON parsing errors.
    """
    _log(log_path, f"[process] xcresult={xcresult_path}")
    # Simple path: always use summary so counts and pie chart work.
    json_str, err_text, cmd_text = run_xcresulttool(xcresult_path)
    _log(log_path, f"[xcresulttool] cmd={cmd_text}")
    if err_text.strip():
        _log(log_path, "[xcresulttool] stderr:\n" + err_text.strip())
    _log(log_path, f"[xcresulttool] stdout_len={len(json_str) if json_str else 0}")

    debug_json_path = str(Path(out_html_path).with_suffix(".json"))
    if json_str:
        try:
            Path(debug_json_path).write_text(json_str, encoding="utf-8")
        except Exception:
            # Do not fail the whole run if we cannot write the debug JSON.
            pass

    if not json_str:
        details = ""
        if cmd_text:
            details += f"Command: {cmd_text}\n\n"
        if err_text.strip():
            details += f"Error output:\n{err_text.strip()}\n"
        else:
            details += "No error output captured."
        raise RuntimeError("Failed to extract summary from xcresult.\n\n" + details)

    try:
        data = json.loads(json_str)
        _log(log_path, f"[json] Successfully parsed JSON, top-level keys: {list(data.keys())[:10] if isinstance(data, dict) else 'not a dict'}")
    except Exception as exc:
        _log(log_path, f"[json] ERROR parsing JSON: {exc}")
        _log(log_path, f"[json] JSON string length: {len(json_str) if json_str else 0}")
        _log(log_path, f"[json] JSON string preview (first 500 chars): {json_str[:500] if json_str else 'None'}")
        raise RuntimeError(f"Failed to parse JSON summary: {exc}") from exc

    passed, failed, skipped = extract_counts(data)
    _log(log_path, f"[counts] passed={passed} failed={failed} skipped={skipped}")
    if passed == 0 and failed == 0 and skipped == 0:
        _log(log_path, "[counts] WARNING: All counts are zero. JSON structure may not match expected patterns.")

    # Detailed path: only from same summary JSON (e.g. testFailures). Does not affect counts.
    details = None
    screenshot_dir_relative = None
    screenshot_map = None
    if include_details:
        details = _extract_details_from_summary(data, log_path)
        if details and include_screenshots:
            screenshot_dir_relative, screenshot_map = _export_attachments(xcresult_path, out_html_path, log_path)
            if not screenshot_map:
                screenshot_map = None

    title = report_title or "XCTest Summary"
    _log(log_path, f"[html] Building HTML with title={title!r}, details_count={len(details) if details else 0}, screenshots={bool(screenshot_map)}")
    html = build_html(
        passed, failed, skipped, Path(xcresult_path).name, title, details,
        screenshot_dir_relative=screenshot_dir_relative,
        screenshot_map=screenshot_map,
    )
    _log(log_path, f"[html] Generated HTML length: {len(html)} bytes")
    _log(log_path, f"[html] HTML contains 'chart.js': {'chart.js' in html.lower()}")
    _log(log_path, f"[html] HTML contains 'canvas': {'canvas' in html.lower()}")
    _log(log_path, f"[html] HTML contains 'Chart(': {'Chart(' in html}")
    if details:
        _log(log_path, f"[html] HTML contains details table: {'<table' in html}")
        _log(log_path, f"[html] HTML contains {html.count('<tr>')} table rows")
    try:
        with open(out_html_path, "w", encoding="utf-8") as f:
            f.write(html)
        _log(log_path, f"[output] Successfully wrote HTML to {out_html_path}")
    except Exception as exc:
        _log(log_path, f"[output] ERROR writing HTML: {exc}")
        raise RuntimeError(f"Failed to write HTML file: {exc}") from exc

    _log(log_path, f"[output] html={out_html_path}")
    _log(log_path, f"[output] extracted_json={debug_json_path}")
    return passed, failed, skipped


def run_cli(
    xcresult_path: str,
    out_html_path: str,
    log_path: Optional[str] = None,
    pdf_output_path: Optional[str] = None,
    report_title: Optional[str] = None,
    include_details: bool = False,
    include_screenshots: bool = False,
) -> int:
    """Run the tool in CLI mode.

    Returns an exit code (0 on success, non-zero on error).
    """
    resolved_log_path = log_path or _default_log_path()
    _log(resolved_log_path, "[cli] starting")
    _log(
        resolved_log_path,
        f"[cli] xcresult={xcresult_path} html={out_html_path} pdf={pdf_output_path} "
        f"title={report_title!r} details={include_details} screenshots={include_screenshots}",
    )
    try:
        passed, failed, skipped = _process_xcresult_to_html(
            xcresult_path=xcresult_path,
            out_html_path=out_html_path,
            log_path=resolved_log_path,
            report_title=report_title,
            include_details=include_details,
            include_screenshots=include_screenshots,
        )
    except Exception as exc:
        _log(resolved_log_path, f"[cli] error: {exc}")
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"XCTest summary for {xcresult_path}:")
    print(f"  Passed : {passed}")
    print(f"  Failed : {failed}")
    print(f"  Skipped: {skipped}")
    print(f"HTML report written to: {out_html_path}")

    if pdf_output_path:
        try:
            from weasyprint import HTML as WeasyHTML  # type: ignore
        except Exception as exc:
            _log(resolved_log_path, f"[cli] weasyprint import_error={exc}")
            print(
                "Warning: WeasyPrint is not available or missing system dependencies; "
                "skipping PDF generation.",
                file=sys.stderr,
            )
            return 0

        try:
            _log(resolved_log_path, f"[cli] Loading HTML file with WeasyPrint: {out_html_path}")
            html_doc = WeasyHTML(filename=out_html_path)
            _log(resolved_log_path, f"[cli] HTML document loaded, writing PDF to {pdf_output_path}")
            html_doc.write_pdf(pdf_output_path)
            _log(resolved_log_path, f"[cli] PDF write completed")
            # Verify PDF was created
            if Path(pdf_output_path).exists():
                pdf_size = Path(pdf_output_path).stat().st_size
                _log(resolved_log_path, f"[cli] PDF file exists, size: {pdf_size} bytes")
                if pdf_size == 0:
                    _log(resolved_log_path, "[cli] WARNING: PDF file is empty (0 bytes)")
            else:
                _log(resolved_log_path, "[cli] WARNING: PDF file was not created")
            _log(resolved_log_path, "[cli] NOTE: WeasyPrint does not execute JavaScript, so Chart.js pie chart will not render in PDF. The chart will only appear when viewing the HTML in a browser.")
        except Exception as exc:
            _log(resolved_log_path, f"[cli] pdf_error={exc}")
            _log(resolved_log_path, f"[cli] Exception type: {type(exc).__name__}")
            import traceback
            _log(resolved_log_path, f"[cli] Traceback:\n{traceback.format_exc()}")
            print(f"Error while generating PDF: {exc}", file=sys.stderr)
            return 1

        print(f"PDF report written to: {pdf_output_path}")

    return 0


def run_xcresulttool(xcresult_path: str) -> Tuple[Optional[str], str, str]:
    """Run xcresulttool to get SUMMARY JSON only. Used for counts and simple report.

    Always prefers the summary command so extract_counts() receives the expected
    schema (passedTests, failedTests, skippedTests). Do not use full bundle JSON
    here or counts will be wrong.

    Returns: (stdout_or_none, stderr_text, command_string)
    """
    xcresult_path = os.path.abspath(xcresult_path)
    xcrun_path = shutil.which("xcrun") or "/usr/bin/xcrun"

    candidates = [
        [xcrun_path, "xcresulttool", "get", "test-results", "summary", "--path", xcresult_path, "--compact"],
        [xcrun_path, "xcresulttool", "get", "--legacy", "--path", xcresult_path, "--format", "json"],
        [xcrun_path, "xcresulttool", "get", "--path", xcresult_path, "--format", "json"],
    ]

    last_stderr = ""
    last_cmd = ""
    for cmd in candidates:
        last_cmd = " ".join(cmd)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            return None, f"Could not execute {cmd[0]}: {exc}", last_cmd

        if result.returncode == 0 and (result.stdout or "").strip():
            return result.stdout, (result.stderr or ""), last_cmd

        if (result.stderr or "").strip():
            last_stderr = result.stderr

    return None, last_stderr, last_cmd

def deep_iter(obj):
    """Recursively yield all dictionaries in a nested dict/list structure."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from deep_iter(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from deep_iter(v)


def extract_counts(data: dict) -> Tuple[int, int, int]:
    """Extract test counts (passed, failed, skipped) from xcresult JSON.

    Xcode versions and output modes vary. This function supports:
      - `xcresulttool get test-results summary` output (often uses `passedTests`, `failedTests`, `skippedTests`,
        and `totalTestCount`) – like the JSON you attached.
      - Older schemas that use `testsPassedCount` / `testsFailedCount` / `testsSkippedCount`
      - Alternate schemas: `passedCount` / `failedCount` / `skippedCount`
      - Any nesting, plus numbers wrapped as {"_value": ...}
    """
    def unwrap(v):
        if isinstance(v, dict) and "_value" in v:
            return v["_value"]
        return v

    for node in deep_iter(data):
        if not isinstance(node, dict):
            continue
        keys = set(node.keys())

        # Pattern 0: summary JSON keys seen in practice (passedTests/failedTests/skippedTests)
        if {"passedTests", "failedTests"}.issubset(keys):
            try:
                p = int(unwrap(node.get("passedTests", 0)) or 0)
                f = int(unwrap(node.get("failedTests", 0)) or 0)
                s = int(unwrap(node.get("skippedTests", 0)) or 0)
                return p, f, s
            except Exception:
                pass

        # Sometimes: totalTestCount + failedTests (+ skippedTests)
        if "totalTestCount" in keys and ("failedTests" in keys or "testsFailedCount" in keys):
            try:
                total = int(unwrap(node.get("totalTestCount", 0)) or 0)
                f = int(unwrap(node.get("failedTests", node.get("testsFailedCount", 0))) or 0)
                s = int(unwrap(node.get("skippedTests", node.get("testsSkippedCount", 0))) or 0)
                p = max(total - f - s, 0)
                return p, f, s
            except Exception:
                pass

        # Pattern A: passed/failed/skipped
        if {"passed", "failed"}.issubset(keys):
            try:
                p = int(unwrap(node.get("passed", 0)) or 0)
                f = int(unwrap(node.get("failed", 0)) or 0)
                s = int(unwrap(node.get("skipped", 0)) or 0)
                return p, f, s
            except Exception:
                pass

        # Pattern B: tests*Count
        if {"testsPassedCount", "testsFailedCount"}.issubset(keys):
            try:
                p = int(unwrap(node.get("testsPassedCount", 0)) or 0)
                f = int(unwrap(node.get("testsFailedCount", 0)) or 0)
                s = int(unwrap(node.get("testsSkippedCount", 0)) or 0)
                return p, f, s
            except Exception:
                pass

        # Alternate: *Count
        if {"passedCount", "failedCount"}.issubset(keys):
            try:
                p = int(unwrap(node.get("passedCount", 0)) or 0)
                f = int(unwrap(node.get("failedCount", 0)) or 0)
                s = int(unwrap(node.get("skippedCount", 0)) or 0)
                return p, f, s
            except Exception:
                pass

    return 0, 0, 0


def _extract_details_from_summary(data: dict, log_path: str) -> Optional[list]:
    """Extract test details only from summary-format JSON (e.g. testFailures).

    Does not touch full bundle format. Returns a list of dicts with name, status,
    suite, and optional failure; or None if nothing found.
    """
    if not isinstance(data, dict):
        return None
    details = []
    _log(log_path, "[details] Extracting from summary JSON only (testFailures)")
    if "testFailures" in data and isinstance(data["testFailures"], list):
        for failure in data["testFailures"]:
            if not isinstance(failure, dict):
                continue
            test_name = failure.get("testName") or failure.get("testIdentifierString") or ""
            test_id = failure.get("testIdentifierString") or failure.get("testIdentifierURL") or ""
            target = failure.get("targetName") or ""
            failure_text = failure.get("failureText") or ""
            if test_name:
                suite = ""
                if test_id and "/" in str(test_id):
                    parts = str(test_id).split("/")
                    suite = parts[-2] if len(parts) >= 2 else target
                details.append({
                    "name": test_name,
                    "status": "Failed",
                    "suite": suite or target,
                    "failure": failure_text[:100] if failure_text else "",
                    "testIdentifierString": test_id or "",
                })
        _log(log_path, f"[details] Found {len(details)} failed tests from testFailures")
    else:
        _log(log_path, "[details] No testFailures in summary (or not a list); detailed list will be empty")
    return details if details else None


def _export_attachments(
    xcresult_path: str,
    out_html_path: str,
    log_path: str,
) -> Tuple[Optional[str], Optional[Dict[str, List[str]]]]:
    """Export attachments (screenshots) from xcresult to a dir next to the HTML file.

    Returns (screenshot_dir_relative_to_html, map of testIdentifier -> [exported filenames])
    or (None, None) on failure or if no attachments. Caller uses relative path for <img src>.
    """
    xcresult_path = os.path.abspath(xcresult_path)
    out_dir = Path(out_html_path).parent
    html_stem = Path(out_html_path).stem
    screenshot_dir_name = f"{html_stem}_screenshots"
    screenshot_abs = out_dir / screenshot_dir_name
    screenshot_abs.mkdir(parents=True, exist_ok=True)

    xcrun_path = shutil.which("xcrun") or "/usr/bin/xcrun"
    cmd = [
        xcrun_path, "xcresulttool", "export", "attachments",
        "--path", xcresult_path,
        "--output-path", str(screenshot_abs),
    ]
    _log(log_path, f"[screenshots] Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    except subprocess.TimeoutExpired:
        _log(log_path, "[screenshots] Export timed out")
        return None, None
    except Exception as exc:
        _log(log_path, f"[screenshots] Export failed: {exc}")
        return None, None

    if result.returncode != 0:
        _log(log_path, f"[screenshots] xcresulttool exit {result.returncode}: {result.stderr or ''}")
        return None, None

    manifest_path = screenshot_abs / "manifest.json"
    if not manifest_path.exists():
        _log(log_path, "[screenshots] No manifest.json; no attachments or different format")
        return screenshot_dir_name, {}  # Dir may have files; no per-test mapping

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log(log_path, f"[screenshots] Failed to parse manifest: {exc}")
        return screenshot_dir_name, {}

    # Build testIdentifier -> [exportedFileName, ...]. Manifest structure varies by Xcode version.
    by_id: Dict[str, List[str]] = {}
    details_list: List = []
    if isinstance(manifest, list):
        details_list = manifest
    elif isinstance(manifest, dict):
        details_list = (
            manifest.get("testAttachmentDetails")
            or manifest.get("testAttachmentDetailsList")
            or manifest.get("attachments")
            or []
        )
    for entry in details_list:
        if not isinstance(entry, dict):
            continue
        test_id = entry.get("testIdentifier") or entry.get("testIdentifierURL") or ""
        attachments = entry.get("attachments") or []
        if not test_id:
            continue
        filenames = []
        for att in attachments:
            if isinstance(att, dict) and att.get("exportedFileName"):
                filenames.append(att["exportedFileName"])
        if filenames:
            by_id[test_id] = filenames
            # Also map by URL if different
            url = entry.get("testIdentifierURL")
            if url and url != test_id:
                by_id[url] = filenames

    _log(log_path, f"[screenshots] Manifest: {len(by_id)} test(s) with attachments")
    return screenshot_dir_name, by_id if by_id else None


def build_html(
    passed: int,
    failed: int,
    skipped: int,
    source_name: str,
    title: str,
    details: Optional[list] = None,
    screenshot_dir_relative: Optional[str] = None,
    screenshot_map: Optional[Dict[str, List[str]]] = None,
) -> str:
    """Construct an HTML report containing test counts, a pie chart, optional details, and optional screenshots.

    The pie chart is drawn via Chart.js loaded from a CDN.  The layout uses
    simple CSS for readability.  The source filename is displayed at the bottom.
    screenshot_map: testIdentifier or testIdentifierURL -> list of exported filenames (in screenshot_dir_relative).
    """
    total = passed + failed + skipped
    # Use f-string to embed numbers; Chart.js will read these values.
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark" />
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                Arial, sans-serif; margin: 32px; background: #1a1a1a; color: #e0e0e0; }}
    .card {{ border: 1px solid #3a3a3a; border-radius: 12px; padding: 20px;
             max-width: 720px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); background: #2b2b2b; }}
    h1, h2 {{ margin: 0 0 8px 0; font-size: 22px; color: #fff; }}
    h2 {{ font-size: 18px; margin-top: 4px; }}
    .meta {{ color: #9ca3af; margin-bottom: 16px; font-size: 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
             margin: 16px 0 12px; }}
    .kpi {{ border: 1px solid #3a3a3a; border-radius: 10px; padding: 12px;
            text-align: center; background: #1f1f1f; }}
    .kpi .label {{ color: #9ca3af; font-size: 12px; }}
    .kpi .value {{ font-size: 20px; margin-top: 6px; color: #fff; }}
    .small {{ color: #9ca3af; font-size: 12px; margin-top: 10px; }}
    canvas {{ max-width: 520px; margin: auto; }}
    table {{ color: #e0e0e0; }}
    th {{ color: #d1d5db; }}
    @media print {{
      body {{ background: #fff !important; color: #111 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      .card {{ background: #fff !important; border-color: #333 !important; box-shadow: none !important; color: #111 !important; }}
      .card * {{ color: #111 !important; }}
      h1, h2 {{ color: #111 !important; }}
      .meta, .small, .kpi .label {{ color: #444 !important; }}
      .kpi {{ background: #f5f5f5 !important; border-color: #ccc !important; color: #111 !important; }}
      .kpi .value {{ color: #111 !important; }}
      table, th, td {{ color: #111 !important; border-color: #333 !important; }}
      td {{ border-bottom-color: #ddd !important; }}
      body > p {{ color: #444 !important; }}
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{title}</h1>
    <div class="meta">This report is intended to be a quick overview of the test results. For detailed test results, please view the original xcresult bundle.</div>
    <div class="grid">
      <div class="kpi"><div class="label">Total</div><div class="value">{total}</div></div>
      <div class="kpi"><div class="label">Passed</div><div class="value">{passed}</div></div>
      <div class="kpi"><div class="label">Failed</div><div class="value">{failed}</div></div>
      <div class="kpi"><div class="label">Skipped</div><div class="value">{skipped}</div></div>
    </div>
    <canvas id="pie" width="520" height="320"></canvas>
    <div class="small">Source: {source_name}</div>
  </div>"""  # Header and summary card

    # Append optional details section.
    if details:
        has_screenshots = bool(screenshot_dir_relative and screenshot_map)
        has_failures = any(item.get("failure") for item in details)
        meta_note = "Screenshots included below when available." if has_screenshots else "Best-effort list of tests discovered in the xcresult summary. Screenshots and other rich attachments are not included."
        html += f"""
  <div class="card" style="margin-top:24px;">
    <h2>Test details</h2>
    <p class="meta">{meta_note}</p>
    <table style="width:100%; border-collapse:collapse; font-size:13px;">
      <thead>
        <tr>
          <th style="text-align:left; border-bottom:1px solid #404040; padding:6px;">Test</th>
          <th style="text-align:left; border-bottom:1px solid #404040; padding:6px;">Suite</th>
          <th style="text-align:left; border-bottom:1px solid #404040; padding:6px;">Status</th>"""
        if has_failures:
            html += """
          <th style="text-align:left; border-bottom:1px solid #404040; padding:6px;">Failure</th>"""
        html += """
        </tr>
      </thead>
      <tbody>
"""
        for item in details:
            name = item.get("name", "")
            suite = item.get("suite", "")
            status = item.get("status", "")
            failure = item.get("failure", "")
            test_id = item.get("testIdentifierString", "")
            status_color = "#ef4444" if status == "Failed" else "#22c55e" if status == "Passed" else "#f59e0b"
            html += f"""        <tr>
          <td style="border-bottom:1px solid #404040; padding:4px 6px;">{name}</td>
          <td style="border-bottom:1px solid #404040; padding:4px 6px;">{suite}</td>
          <td style="border-bottom:1px solid #404040; padding:4px 6px; color:{status_color}; font-weight:bold;">{status}</td>"""
            if has_failures:
                html += f"""
          <td style="border-bottom:1px solid #404040; padding:4px 6px; font-size:12px; color:#9ca3af;">{failure}</td>"""
            html += """
        </tr>
"""
            # Optional screenshot row: match by testIdentifierString or testIdentifierURL
            if has_screenshots and screenshot_map:
                imgs = screenshot_map.get(test_id)
                if not imgs:
                    for key in screenshot_map:
                        if test_id in key or key.endswith(test_id) or (test_id and key.split("/")[-1] == test_id.split("/")[-1]):
                            imgs = screenshot_map[key]
                            break
                if imgs:
                    colspan = 4 if has_failures else 3
                    html += f"""        <tr>
          <td colspan="{colspan}" style="border-bottom:1px solid #404040; padding:8px 6px; background:#1f1f1f;">
            <div style="font-size:11px; color:#9ca3af; margin-bottom:4px;">Screenshots</div>
            <div style="display:flex; flex-wrap:wrap; gap:8px;">"""
                    for fn in imgs[:10]:
                        src = f"{screenshot_dir_relative}/{fn}"
                        html += f'<img src="{src}" alt="{fn}" style="max-width:280px; max-height:200px; border:1px solid #404040; border-radius:4px;" />'
                    if len(imgs) > 10:
                        html += f'<span style="font-size:12px; color:#9ca3af;">+{len(imgs)-10} more</span>'
                    html += """</div>
          </td>
        </tr>
"""
        html += """      </tbody>
    </table>
  </div>
"""

    # Close the document (Chart.js script: must interpolate passed/failed/skipped).
    html += f"""
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script>
    Chart.defaults.color = '#d1d5db';
    Chart.defaults.borderColor = '#404040';
    const ctx = document.getElementById('pie');
    new Chart(ctx, {{
      type: 'pie',
      data: {{
        labels: ['Passed', 'Failed', 'Skipped'],
        datasets: [{{ data: [{passed}, {failed}, {skipped}],
          backgroundColor: ['#22c55e', '#ef4444', '#f59e0b'],
          borderColor: '#2b2b2b',
          borderWidth: 2 }}]
      }},
      options: {{
        responsive: true,
        plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#d1d5db' }} }}, title: {{ display: false }} }}
      }}
    }});
  </script>
  <hr style="border: none; border-top: 1px solid #404040; margin: 24px 0 0 0;" />
  <br /><br /><br />
  <p style="color: #6b7280; font-size: 12px; margin: 0;">This was built with passion</p>
</body>
</html>
"""
    return html


class XCResultGUI:
    """Encapsulates the Tkinter GUI for processing xcresult bundles."""
    def __init__(self):
        if _DND_AVAILABLE:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()
        self.root.title("HTML Report Generator for Xcode Test Results")
        self.root.geometry("600x500")
        # Force dark appearance on macOS
        try:
            # Set dark mode appearance (macOS 10.14+)
            self.root.tk.call("::tk::unsupported::MacWindowStyle", "style", self.root._w, "dark", "dark")
        except Exception:
            pass
        # Configure dark theme colors
        try:
            style = ttk.Style()
            style.theme_use("clam")  # Use a theme that supports customization
            # Configure dark colors
            style.configure("TFrame", background="#2b2b2b")
            style.configure("TLabel", background="#2b2b2b", foreground="#ffffff")
            style.configure("TEntry", fieldbackground="#3c3c3c", foreground="#ffffff")
            style.configure("TButton", background="#4a4a4a", foreground="#ffffff")
            style.configure("TCheckbutton", background="#2b2b2b", foreground="#ffffff")
            self.root.configure(bg="#2b2b2b")
        except Exception:
            pass
        # variables
        default_xc = _default_xcresult_path()
        self.xcresult_path = tk.StringVar(value=default_xc or "")
        self.output_path = tk.StringVar(value=_default_output_path())
        self.log_path = tk.StringVar(value=_default_log_path())
        self.report_title = tk.StringVar(value="XCTest Summary")
        self.include_details = tk.BooleanVar(value=False)
        # self.include_screenshots = tk.BooleanVar(value=False)  # Screenshot UI commented out
        _log(self.log_path.get(), f"[startup] dnd_available={_DND_AVAILABLE} weasy_available={_WEASY_AVAILABLE}")
        _log(self.log_path.get(), f"[startup] python={sys.executable} cwd={os.getcwd()}")
        # Build UI
        self._build_widgets()

    def _build_widgets(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        # Drag and drop area or file selection
        drop_lbl = ttk.Label(frm, text="1. Drag & drop your .xcresult here",
                              relief=tk.RIDGE, padding=20, anchor="center")
        drop_lbl.pack(fill=tk.X, padx=5, pady=5)
        if _DND_AVAILABLE:
            drop_lbl.drop_target_register(DND_FILES)
            drop_lbl.dnd_bind('<<Drop>>', self._on_drop)
        else:
            drop_lbl.configure(text="1. Browse to your .xcresult (tkinterdnd2 not installed)")
        # Path entry + browse button
        path_frame = ttk.Frame(frm)
        path_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Entry(path_frame, textvariable=self.xcresult_path, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(path_frame, text="Browse…", command=self._browse_xcresult).pack(side=tk.LEFT, padx=5)
        # Output entry + choose button
        out_frame = ttk.Frame(frm)
        out_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(out_frame, text="2. HTML output path:").pack(side=tk.LEFT)
        ttk.Entry(out_frame, textvariable=self.output_path, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(out_frame, text="Choose…", command=self._choose_output).pack(side=tk.LEFT)
        # Log file path
        log_frame = ttk.Frame(frm)
        log_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(log_frame, text="3. Log file path:").pack(side=tk.LEFT)
        ttk.Entry(log_frame, textvariable=self.log_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(log_frame, text="Choose…", command=self._choose_log_path).pack(side=tk.LEFT)

        # Report title
        title_frame = ttk.Frame(frm)
        title_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(title_frame, text="4. Report title (optional):").pack(side=tk.LEFT)
        ttk.Entry(title_frame, textvariable=self.report_title).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Detailed report toggle
        details_frame = ttk.Frame(frm)
        details_frame.pack(fill=tk.X, padx=5, pady=5)
        self.details_cb = ttk.Checkbutton(
            details_frame,
            text="Include detailed test list in HTML report",
            variable=self.include_details,
        )
        self.details_cb.pack(side=tk.LEFT)
        # Screenshot functionality commented out (was: only enabled when detailed list is included)
        # self.screenshots_cb = ttk.Checkbutton(
        #     details_frame,
        #     text="Include screenshots",
        #     variable=self.include_screenshots,
        #     state="disabled",
        # )
        # self.screenshots_cb.pack(side=tk.LEFT, padx=(20, 0))
        # self._on_include_details_changed()

        # Buttons
        btn_frame = ttk.Frame(frm)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text="Generate HTML", command=self._generate_html).pack(side=tk.LEFT, padx=5)
        # Export PDF button is hidden because PDF export is unreliable in this packaged app.
        # self.pdf_button = ttk.Button(btn_frame, text="Export PDF", command=self._export_pdf)
        # self.pdf_button.pack(side=tk.LEFT, padx=5)

        # Status label - light blue for dark theme visibility
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(frm, textvariable=self.status_var)
        status_label.pack(fill=tk.X)
        # Configure light blue foreground for dark theme
        try:
            status_label.configure(foreground="#5dade2")  # Light blue
        except Exception:
            pass

        # Progress bar (spinner) shown while processing
        self.progress = ttk.Progressbar(frm, mode="indeterminate")

    def _start_spinner(self):
        """Show and start the indeterminate progress bar."""
        try:
            if not self.progress.winfo_ismapped():
                self.progress.pack(fill=tk.X, padx=5, pady=(4, 0))
            self.progress.start(80)
            self.root.update_idletasks()
        except Exception:
            pass

    def _stop_spinner(self):
        """Stop and hide the progress bar."""
        try:
            self.progress.stop()
            if self.progress.winfo_ismapped():
                self.progress.pack_forget()
            self.root.update_idletasks()
        except Exception:
            pass

    def _finish_success(self, out_path: str):
        """Stop spinner and show success UI after generation completes."""
        self._stop_spinner()
        self.status_var.set(f"Generated HTML at {out_path}")
        messagebox.showinfo(
            "Success",
            f"HTML report generated:\n{out_path}\n"
            "You can now open this file in a browser and print it to PDF.",
        )

    def _on_drop(self, event):
        # Accept only the first file from drop
        files = self.root.tk.splitlist(event.data)
        if files:
            path = files[0]
            if path.endswith(".xcresult"):
                self.xcresult_path.set(path)
            else:
                messagebox.showwarning("Invalid file", "Please drop a .xcresult bundle.")

    def _browse_xcresult(self):
        path = filedialog.askopenfilename(title="Select .xcresult bundle",
                                          filetypes=[("XCResult bundles", "*.xcresult"), ("All files", "*")])
        if path:
            self.xcresult_path.set(path)

    def _choose_output(self):
        initial = self.output_path.get() or _default_output_path()
        path = filedialog.asksaveasfilename(
            title="Choose HTML output file",
            defaultextension=".html",
            filetypes=[("HTML files", "*.html")],
            initialdir=str(Path(initial).parent) if initial else str(_default_output_dir()),
            initialfile=Path(initial).name if initial else "report.html",
        )
        if path:
            self.output_path.set(path)

    # Screenshot UI: enable/disable screenshot checkbox when details toggled (commented out)
    # def _on_include_details_changed(self):
    #     if self.include_details.get():
    #         self.screenshots_cb.configure(state="normal")
    #     else:
    #         self.include_screenshots.set(False)
    #         self.screenshots_cb.configure(state="disabled")

    def _choose_log_path(self):
        path = filedialog.asksaveasfilename(
            title="Choose log output file",
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("All files", "*")],
            initialfile=Path(self.log_path.get()).name if self.log_path.get() else "xcresult_gui.log",
        )
        if path:
            self.log_path.set(path)


    def _generate_html(self):
        xc_path = self.xcresult_path.get()
        out_path = self.output_path.get()
        if not xc_path:
            messagebox.showerror("Missing input", "Please select an .xcresult bundle first.")
            return
        if not out_path:
            messagebox.showerror("Missing output", "Please choose where to save the HTML file.")
            return
        out_path = _next_available_report_path(out_path)
        if out_path != self.output_path.get():
            self.output_path.set(out_path)
        # Random minimum spinner duration between 2 and 5 seconds
        min_spinner_seconds = random.uniform(2.0, 5.0)
        start_time = time.time()
        # Run xcresulttool and parse counts
        self.status_var.set("Extracting summary…")
        self.root.update_idletasks()
        self._start_spinner()
        _log(self.log_path.get(), f"[generate] xcresult={xc_path}")
        try:
            passed, failed, skipped = _process_xcresult_to_html(
                xcresult_path=xc_path,
                out_html_path=out_path,
                log_path=self.log_path.get(),
                report_title=(self.report_title.get().strip() or None),
                include_details=bool(self.include_details.get()),
                include_screenshots=False,  # Screenshot UI commented out
            )
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            self.status_var.set("Error generating HTML")
            self._stop_spinner()
            return

        # Ensure spinner stays visible for at least the random minimum duration
        elapsed = time.time() - start_time
        remaining_ms = max(0, int((min_spinner_seconds - elapsed) * 1000))
        if remaining_ms > 0:
            self.root.after(remaining_ms, lambda: self._finish_success(out_path))
        else:
            self._finish_success(out_path)

    def _export_pdf(self):
        try:
            from weasyprint import HTML as WeasyHTML  # type: ignore
        except Exception as exc:
            messagebox.showerror(
                "Unavailable",
                "WeasyPrint is not installed or is missing system dependencies.\n\n"
                "Install/repair it, or print the HTML to PDF from your browser.\n\n"
                f"Import error: {exc}",
            )
            _log(self.log_path.get(), f"[weasyprint] import_error={exc}")
            return
        out_html = self.output_path.get()
        if not out_html or not Path(out_html).exists():
            messagebox.showerror("Missing HTML", "Generate an HTML report first.")
            return
        pdf_path = filedialog.asksaveasfilename(title="Choose PDF output file",
                                                defaultextension=".pdf",
                                                filetypes=[("PDF files", "*.pdf")],
                                                initialfile="report.pdf")
        if not pdf_path:
            return
        self.status_var.set("Converting to PDF…")
        self.root.update_idletasks()
        _log(self.log_path.get(), f"[pdf] Starting PDF conversion from {out_html} to {pdf_path}")
        try:
            # Use WeasyPrint to convert HTML to PDF
            _log(self.log_path.get(), "[pdf] Loading HTML file with WeasyPrint")
            html_doc = WeasyHTML(filename=out_html)
            _log(self.log_path.get(), f"[pdf] HTML document loaded, writing PDF to {pdf_path}")
            html_doc.write_pdf(pdf_path)
            _log(self.log_path.get(), f"[pdf] PDF successfully written to {pdf_path}")
            # Verify PDF was created
            if Path(pdf_path).exists():
                pdf_size = Path(pdf_path).stat().st_size
                _log(self.log_path.get(), f"[pdf] PDF file exists, size: {pdf_size} bytes")
            else:
                _log(self.log_path.get(), "[pdf] WARNING: PDF file was not created")
        except Exception as exc:
            _log(self.log_path.get(), f"[pdf] ERROR during PDF conversion: {exc}")
            _log(self.log_path.get(), f"[pdf] Exception type: {type(exc).__name__}")
            import traceback
            _log(self.log_path.get(), f"[pdf] Traceback:\n{traceback.format_exc()}")
            messagebox.showerror("Error", f"Failed to generate PDF: {exc}")
            self.status_var.set("Error generating PDF")
            return
        self.status_var.set(f"PDF exported at {pdf_path}")
        messagebox.showinfo("Success", f"PDF generated:\n{pdf_path}")

    def run(self):
        self.root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract a minimal test summary from an .xcresult bundle and render it to HTML (and optionally PDF).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode instead of opening the GUI.",
    )
    parser.add_argument(
        "xcresult",
        nargs="?",
        help="Path to the .xcresult bundle (required in CLI mode).",
    )
    parser.add_argument(
        "--output-html",
        help="Path where the HTML report should be written (required in CLI mode).",
    )
    parser.add_argument(
        "--log-path",
        help="Optional path to a log file (CLI mode). Defaults to a timestamped file in your home directory.",
    )
    parser.add_argument(
        "--pdf-output",
        help="Optional path for a PDF report (CLI mode). Requires WeasyPrint.",
    )
    parser.add_argument(
        "--title",
        help="Optional report title to display in the HTML report.",
    )
    parser.add_argument(
        "--include-details",
        action="store_true",
        help="Include a best-effort detailed test list in the HTML report.",
    )
    parser.add_argument(
        "--include-screenshots",
        action="store_true",
        help="Include exported screenshots in the report (only with --include-details).",
    )

    args = parser.parse_args(argv)

    if args.cli:
        if not args.xcresult or not args.output_html:
            parser.error("--cli requires an .xcresult path and --output-html.")

        exit_code = run_cli(
            xcresult_path=args.xcresult,
            out_html_path=args.output_html,
            log_path=args.log_path,
            pdf_output_path=args.pdf_output,
            report_title=args.title,
            include_details=bool(args.include_details),
            include_screenshots=bool(args.include_screenshots) if args.include_details else False,
        )
        raise SystemExit(exit_code)

    # Default: launch the GUI.
    app = XCResultGUI()
    app.run()


if __name__ == '__main__':
    main()