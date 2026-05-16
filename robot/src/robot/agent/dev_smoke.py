"""Dev smoke test: capture mic audio and print on wake-word detection.

Usage:
    python -m robot.agent.dev_smoke

Env vars:
    BUGGSY_WAKE_MODEL  Path to an openWakeWord .onnx model file.
                       Default: robot/wake_models/hey_jarvis_v0.1.onnx
    BUGGSY_WAKE_THRESHOLD  Detection threshold 0.0-1.0. Default: 0.5
    BUGGSY_VAD_THRESHOLD   Silero VAD threshold 0.0-1.0; 0 disables. Default: 0 (off).
                           Filters false-positive wake events but adds CPU cost.
    BUGGSY_SPEEX_NS        Set to 1 to enable Speex noise suppression (needs speexdsp-ns).
    BUGGSY_AUDIO_DEVICE    sounddevice input device index or name.
"""

from __future__ import annotations

import asyncio
import logging
import os

from shared.protocol import WakeEvent

from .audio_bus import AudioBus
from .wake_detector import OpenWakeWordDetector, run_wake_detection

DEFAULT_MODEL = "robot/wake_models/hey_jarvis_v0.1.onnx"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    model_path = os.environ.get("BUGGSY_WAKE_MODEL", DEFAULT_MODEL)
    threshold = float(os.environ.get("BUGGSY_WAKE_THRESHOLD", "0.5"))
    vad_threshold = float(os.environ.get("BUGGSY_VAD_THRESHOLD", "0"))
    speex_ns = os.environ.get("BUGGSY_SPEEX_NS", "0") == "1"
    device_env = os.environ.get("BUGGSY_AUDIO_DEVICE")
    device: int | str | None = None
    if device_env:
        device = int(device_env) if device_env.isdigit() else device_env

    detector = OpenWakeWordDetector(
        model_path=model_path,
        threshold=threshold,
        vad_threshold=vad_threshold,
        enable_speex_noise_suppression=speex_ns,
    )
    bus = AudioBus(device=device)
    bus.start()

    async def on_wake(evt: WakeEvent) -> None:
        print(f"WAKE! confidence={evt.confidence:.3f} ts={evt.ts:.3f}")

    print(
        f"Listening with model={model_path} threshold={threshold} "
        f"vad_threshold={vad_threshold} speex_ns={speex_ns} (Ctrl-C to stop)"
    )
    try:
        await run_wake_detection(bus, detector, on_wake)
    finally:
        bus.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
