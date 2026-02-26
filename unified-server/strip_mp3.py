#!/usr/bin/env python3
"""
Strip redundant metadata from MP3 files using ffmpeg.

Usage:
  python3 strip_mp3.py input.mp3 [output.mp3]
  python3 strip_mp3.py input.mp3   -> writes input_stripped.mp3

Requires ffmpeg on PATH.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def strip_mp3(input_path: Path, output_path: Path) -> None:
    """Run ffmpeg to copy audio stream and drop all metadata."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg not found. Install ffmpeg and ensure it is on PATH.")

    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if input_path.suffix.lower() != ".mp3":
        raise ValueError(f"Expected .mp3 file, got: {input_path.suffix}")

    cmd = [
        ffmpeg,
        "-y",
        "-i", str(input_path),
        "-map", "0:a:0",
        "-c", "copy",
        "-map_metadata", "-1",
        "-write_id3v2", "0",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr or result.stdout}")

    if not output_path.is_file():
        raise RuntimeError("ffmpeg did not produce output file.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strip metadata from an MP3 file (no re-encode)."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input MP3 file path",
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=None,
        help="Output MP3 path (default: <input_stem>_stripped.mp3)",
    )
    args = parser.parse_args()

    input_path = args.input.resolve()
    output_path = args.output.resolve() if args.output else input_path.parent / f"{input_path.stem}_stripped.mp3"

    try:
        strip_mp3(input_path, output_path)
        print(f"Done: {output_path}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
