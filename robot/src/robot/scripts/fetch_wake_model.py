"""Download an openWakeWord pretrained model into robot/wake_models/.

Wraps openwakeword's bundled downloader, locates the downloaded file inside
the installed package, and copies it to a path the dev_smoke default expects.

Usage:
    python -m robot.scripts.fetch_wake_model
    python -m robot.scripts.fetch_wake_model --model hey_jarvis_v0.1
    python -m robot.scripts.fetch_wake_model --dest /tmp/wake_models
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

DEFAULT_MODEL = "hey_jarvis_v0.1"
DEFAULT_DEST = Path("robot/wake_models")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="openWakeWord model name (without .onnx)")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="Destination directory")
    args = parser.parse_args()

    try:
        import openwakeword
        import openwakeword.utils
    except ImportError as e:
        print(f"openwakeword not installed: {e}", file=sys.stderr)
        return 1

    print("Downloading openWakeWord pretrained models (one-time)...")
    openwakeword.utils.download_models()

    # Locate the downloaded .onnx files inside the installed package.
    pkg_dir = Path(openwakeword.__file__).parent
    candidates = list(pkg_dir.rglob(f"{args.model}.onnx"))
    if not candidates:
        print(f"Could not find {args.model}.onnx under {pkg_dir}", file=sys.stderr)
        print("Available .onnx files:", file=sys.stderr)
        for p in pkg_dir.rglob("*.onnx"):
            print(f"  {p}", file=sys.stderr)
        return 2

    src = candidates[0]
    args.dest.mkdir(parents=True, exist_ok=True)
    dest = args.dest / f"{args.model}.onnx"
    shutil.copy2(src, dest)
    print(f"Copied {src} -> {dest}")
    print(f"Set BUGGSY_WAKE_MODEL={dest} or pass --model to dev_smoke.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
