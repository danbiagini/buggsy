"""Post-wake utterance capture.

After the agent wakes, record from the AudioBus until the speaker stops
(a run of low-energy frames) or a hard time cap, then hand back a WAV
the orchestrator can ship to the STT service.

Silence detection is energy-based (RMS) rather than a VAD model — zero
extra CPU on the CM4, and the hard cap backstops it. If RMS proves too
noisy in practice, swapping in a VAD here is a localized change.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave

import numpy as np

from .audio_bus import AudioBus, Subscription

log = logging.getLogger(__name__)

SAMPLE_WIDTH_BYTES = 2  # int16


def frame_rms(frame: bytes) -> float:
    """Root-mean-square amplitude of an int16 PCM frame."""
    samples = np.frombuffer(frame, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    # float64 accumulation to avoid int16 overflow in the square.
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def frame_seconds(frame: bytes, sample_rate: int) -> float:
    return (len(frame) // SAMPLE_WIDTH_BYTES) / sample_rate


def frames_to_wav(frames: list[bytes], sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SAMPLE_WIDTH_BYTES)
        w.setframerate(sample_rate)
        w.writeframes(b"".join(frames))
    return buf.getvalue()


class UtteranceCapturer:
    def __init__(
        self,
        bus: AudioBus,
        *,
        max_seconds: float,
        silence_seconds: float,
        silence_rms: float,
    ) -> None:
        self._bus = bus
        self._max_seconds = max_seconds
        self._silence_seconds = silence_seconds
        self._silence_rms = silence_rms

    async def capture(self) -> bytes | None:
        """Record one utterance. Returns WAV bytes, or None if nothing
        was captured. Uses its own short-lived subscription so wake
        detection's stream is untouched."""
        sub = self._bus.subscribe()
        try:
            frames = await self._collect(sub)
        finally:
            self._bus.unsubscribe(sub)
        if not frames:
            return None
        return frames_to_wav(frames, self._bus.sample_rate)

    async def _collect(self, sub: Subscription) -> list[bytes]:
        frames: list[bytes] = []
        captured_s = 0.0
        silence_s = 0.0
        sr = self._bus.sample_rate
        while captured_s < self._max_seconds:
            remaining = self._max_seconds - captured_s
            try:
                frame = await asyncio.wait_for(sub.queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                # Mic stalled or hit the cap mid-wait — stop with what we have.
                break
            frames.append(frame)
            captured_s += frame_seconds(frame, sr)
            if frame_rms(frame) < self._silence_rms:
                silence_s += frame_seconds(frame, sr)
                if silence_s >= self._silence_seconds:
                    break
            else:
                silence_s = 0.0
        log.info("utterance: %.2fs captured (%d frames)", captured_s, len(frames))
        return frames
