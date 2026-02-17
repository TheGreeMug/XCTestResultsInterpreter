#!/bin/bash
# Build a standalone macOS .app for XCResult HTML Generator.
# Requires: pip install -r requirements-build.txt
# The .app will be in dist/XCResult Report.app

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use the first Python that has PyInstaller (pip may have installed it for 3.12 while python3 is 3.13)
PYTHON_CMD=""
for py in python3.12 python3.11 python3; do
  if command -v "$py" &>/dev/null && "$py" -m PyInstaller --help &>/dev/null; then
    PYTHON_CMD="$py"
    break
  fi
done
if [ -z "$PYTHON_CMD" ]; then
  echo "PyInstaller not found. Install with: pip install -r requirements-build.txt"
  echo "Use the same Python for pip and for this script (e.g. pip3.12 install -r requirements-build.txt then run ./build_app.sh)."
  exit 1
fi
echo "Using: $PYTHON_CMD"

ADD_DATA=""
if [ -e "xcresults" ]; then
  echo "Packing 'xcresults' into the app (optional sample/demo bundle)."
  ADD_DATA="--add-data xcresults:."
fi

# Optional app icon. Use existing .icns or create one from xctest_result.png / icon.png.
ICON_ARG=""
if [ ! -e "icon.icns" ] && [ ! -e "XCResult Report.icns" ] && [ ! -e "app.icns" ]; then
  for png in "xctest_result.png" "icon.png"; do
    if [ -e "$png" ]; then
      echo "Creating icon.icns from $png"
      ICONSET="icon.iconset"
      mkdir -p "$ICONSET"
      for size in 16 32 128 256 512; do
        sips -z $size $size "$png" --out "$ICONSET/icon_${size}x${size}.png" 2>/dev/null || true
        s2=$((size * 2))
        sips -z $s2 $s2 "$png" --out "$ICONSET/icon_${size}x${size}@2x.png" 2>/dev/null || true
      done
      iconutil -c icns "$ICONSET" -o icon.icns 2>/dev/null && rm -rf "$ICONSET" || rm -rf "$ICONSET"
      break
    fi
  done
fi
for icns in "icon.icns" "XCResult Report.icns" "app.icns"; do
  if [ -e "$icns" ]; then
    ICON_ARG="--icon $icns"
    echo "Using icon: $icns"
    break
  fi
done

"$PYTHON_CMD" -m PyInstaller \
  --windowed \
  --name "XCResult Report" \
  --onefile \
  --clean \
  $ICON_ARG \
  $ADD_DATA \
  xcresult_gui_v6.py

echo ""
echo "Done. App: dist/XCResult Report.app"
echo "Copy that folder to another Mac; they need Xcode (or xcresulttool) installed to use it."
echo ""
if [ -n "$ADD_DATA" ]; then
  echo "The app includes the packed 'xcresults' file; it will be pre-selected when you open the app."
else
  echo "To use a sample without packing: put a file or folder named 'xcresults' next to the app; the app will pre-fill it when present."
fi
