"""Probe per-component CPU cost of openWakeWord on this host.

Calls openWakeWord with timing=True and prints rolling averages every 5s for
the preprocessor, VAD (if enabled), and each wake model.

Use this to decide whether the wake model dominates the CPU budget (in
which case a true VAD *gate* — e.g. webrtcvad before calling predict() —
will help) or whether the preprocessor / VAD itself is the bottleneck.

Usage:
    python -m robot.scripts.timing_probe
    BUGGSY_VAD_THRESHOLD=0.5 python -m robot.scripts.timing_probe
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict

import numpy as np

from robot.agent.audio_bus import AudioBus

DEFAULT_MODEL = "robot/wake_models/hey_jarvis_v0.1.onnx"
REPORT_EVERY_S = 5.0


async def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    from openwakeword.model import Model

    model_path = os.environ.get("BUGGSY_WAKE_MODEL", DEFAULT_MODEL)
    vad_threshold = float(os.environ.get("BUGGSY_VAD_THRESHOLD", "0.0"))
    speex_ns = os.environ.get("BUGGSY_SPEEX_NS", "0") == "1"

    print(f"Loading model={model_path} vad_threshold={vad_threshold} speex_ns={speex_ns}")
    model = Model(
        wakeword_models=[model_path],
        inference_framework="onnx",
        vad_threshold=vad_threshold,
        enable_speex_noise_suppression=speex_ns,
    )

    bus = AudioBus()
    bus.start()
    sub = bus.subscribe()

    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    frame_count = 0
    last_report = time.time()
    start = last_report

    try:
        async for frame in sub.frames():
            audio = np.frombuffer(frame, dtype=np.int16)
            _scores, timing = model.predict(audio, timing=True)
            frame_count += 1
            for component, secs in timing.get("models", {}).items():
                totals[component] += secs
                counts[component] += 1

            now = time.time()
            if now - last_report >= REPORT_EVERY_S:
                wall = now - start
                print(f"\n--- {wall:6.1f}s elapsed, {frame_count} frames ---")
                print(f"{'component':<20} {'avg_ms':>8} {'p_frame':>8} {'cpu_share':>10}")
                # Each frame represents 80ms of wall audio; cpu_share = (avg_ms / 80) * 100
                for comp in sorted(totals):
                    avg_ms = (totals[comp] / counts[comp]) * 1000
                    share = (avg_ms / 80.0) * 100
                    print(f"{comp:<20} {avg_ms:>8.2f} {counts[comp]:>8d} {share:>9.1f}%")
                last_report = now
    finally:
        bus.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
