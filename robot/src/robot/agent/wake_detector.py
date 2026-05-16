"""Wake-word detection backed by openWakeWord.

Conforms to the `shared.protocol.WakeDetector` Protocol via `detect()`. A
helper `run_wake_detection()` consumes frames from an AudioBus subscription
and invokes a callback on each (debounced) wake event.
"""

from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

import numpy as np

from shared.protocol import WakeEvent

from .audio_bus import AudioBus

log = logging.getLogger(__name__)


class OpenWakeWordDetector:
    def __init__(self, model_path: str, threshold: float = 0.5) -> None:
        from openwakeword.model import Model

        self._model = Model(wakeword_models=[model_path], inference_framework="onnx")
        self._threshold = threshold
        self.model_path = model_path

    def detect(self, frame: bytes) -> WakeEvent | None:
        audio = np.frombuffer(frame, dtype=np.int16)
        scores = self._model.predict(audio)
        best_score = 0.0
        for score in scores.values():
            if score > best_score:
                best_score = float(score)
        if best_score >= self._threshold:
            return WakeEvent(ts=time.time(), confidence=best_score)
        return None


async def run_wake_detection(
    bus: AudioBus,
    detector: OpenWakeWordDetector,
    on_wake: Callable[[WakeEvent], Awaitable[None]],
    debounce_s: float = 2.0,
) -> None:
    sub = bus.subscribe()
    last_wake_ts = 0.0
    async for frame in sub.frames():
        evt = detector.detect(frame)
        if evt is None:
            continue
        if evt.ts - last_wake_ts < debounce_s:
            continue
        last_wake_ts = evt.ts
        await on_wake(evt)
