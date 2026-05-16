"""Pre-test environment check for the robot.

Run on the Reachy Mini before invoking dev_smoke. Verifies:
- Python version (>= 3.12).
- PortAudio + sounddevice see an input device.
- openwakeword + onnxruntime import cleanly.

Usage:
    python -m robot.scripts.preflight
"""

from __future__ import annotations

import sys


def check_python() -> bool:
    ok = sys.version_info >= (3, 12)
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] Python {sys.version.split()[0]} (need >= 3.12)")
    return ok


def check_sounddevice() -> bool:
    try:
        import sounddevice as sd
    except OSError as e:
        print(f"[FAIL] sounddevice import failed: {e}")
        print("       Try: sudo apt install -y libportaudio2")
        return False
    except ImportError as e:
        print(f"[FAIL] sounddevice not installed: {e}")
        return False

    devices = sd.query_devices()
    inputs = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    if not inputs:
        print("[FAIL] No input audio devices found")
        return False

    print(f"[OK]   {len(inputs)} input device(s) found:")
    for i, d in inputs:
        default = " (default)" if i == sd.default.device[0] else ""
        print(f"         [{i}] {d['name']}  in={d['max_input_channels']}ch  sr={int(d['default_samplerate'])}{default}")
    return True


def check_openwakeword() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError as e:
        print(f"[FAIL] onnxruntime import failed: {e}")
        return False
    try:
        import openwakeword  # noqa: F401
        from openwakeword.model import Model  # noqa: F401
    except ImportError as e:
        print(f"[FAIL] openwakeword import failed: {e}")
        return False
    print("[OK]   openwakeword + onnxruntime import cleanly (ONNX backend)")
    return True


def main() -> int:
    print("Buggsy robot preflight check\n")
    results = [
        check_python(),
        check_sounddevice(),
        check_openwakeword(),
    ]
    print()
    if all(results):
        print("All checks passed. You can run: python -m robot.agent.dev_smoke")
        return 0
    print("One or more checks failed. Fix the above before running dev_smoke.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
