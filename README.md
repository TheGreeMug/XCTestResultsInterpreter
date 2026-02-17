# XCTestResultsInterpreter
Python GUI and CLI for turning Xcode `.xcresult` bundles into HTML test reports. Extracts passed/failed/skipped counts via `xcrun xcresulttool`, renders a summary with a Chart.js pie chart, and optionally exports to PDF. Use the Tkinter GUI (with drag-and-drop) or run from the command line for CI. macOS only; can be packaged as a standalone app.
