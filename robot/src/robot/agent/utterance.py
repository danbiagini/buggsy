"""Post-wake utterance capture.

A single long-lived AudioBus subscription continuously buffers the most
recent `preroll_seconds` of audio. On wake the capturer stops discarding
and keeps recording the *same* stream into the utterance — so there's no
gap between the pre-roll and the live capture, and words spoken into the
wake-word detection lag (e.g. "hey jarvis what time is it" in one breath)
aren't lost or clipped.

Silence detection is energy-based (RMS) rather than a VAD model — zero
extra CPU on the CM4, and the hard cap backstops it. If RMS proves too
noisy in practice, swapping in a VAD here is a localized change.
"""

from __future__ import annotations

import asyncio
import io
import logging
import math
import wave
from collections import deque

import numpy as np

from .audio_bus import AudioBus

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
        preroll_seconds: float,
        lead_in_seconds: float,
        max_seconds: float,
        silence_seconds: float,
        silence_rms: float,
    ) -> None:
        self._bus = bus
        self._preroll_maxlen = max(1, math.ceil(preroll_seconds * 1000 / bus.frame_ms))
        self._lead_in_seconds = lead_in_seconds
        self._max_seconds = max_seconds
        self._silence_seconds = silence_seconds
        self._silence_rms = silence_rms
        self._sub = None
        self._task: asyncio.Task | None = None
        self._busy = False
        self._pending: asyncio.Future[bytes | None] | None = None

    @property
    def busy(self) -> bool:
        return self._busy

    def start(self) -> None:
        # Roomy queue: the consumer always drains, but give headroom so a
        # brief scheduling hiccup during capture never drops frames.
        self._sub = self._bus.subscribe(max_queue=64)
        self._task = asyncio.create_task(self._run(), name="utterance")

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
        if self._sub is not None:
            self._bus.unsubscribe(self._sub)

    def arm(self) -> "asyncio.Future[bytes | None]":
        """Start capturing on the next frames. Returns a future that
        resolves to the utterance WAV bytes, or None for a bare wake
        (no speech in the lead-in) the caller should treat as a greeting
        prompt."""
        self._pending = asyncio.get_running_loop().create_future()
        self._busy = True
        return self._pending

    async def _run(self) -> None:
        assert self._sub is not None
        preroll: deque[bytes] = deque(maxlen=self._preroll_maxlen)
        async for frame in self._sub.frames():
            if not self._busy:
                preroll.append(frame)
                continue
            # Armed: `frame` is the first post-wake frame, contiguous with
            # the preroll (same subscription — no boundary gap).
            result = await self._capture(list(preroll), frame)
            preroll.clear()
            if self._pending is not None and not self._pending.done():
                self._pending.set_result(result)
            self._pending = None
            self._busy = False

    async def _capture(self, preroll_frames: list[bytes], first_frame: bytes) -> bytes | None:
        assert self._sub is not None
        frames: list[bytes] = []
        elapsed_s = 0.0       # all post-wake audio seen (incl. pre-speech)
        recorded_s = 0.0      # audio kept (post speech onset)
        silence_s = 0.0
        seen_speech = False
        sr = self._bus.sample_rate
        frame: bytes | None = first_frame

        while frame is not None:
            fs = frame_seconds(frame, sr)
            elapsed_s += fs
            is_silent = frame_rms(frame) < self._silence_rms

            if not seen_speech and not is_silent:
                seen_speech = True

            if seen_speech:
                frames.append(frame)
                recorded_s += fs
                if is_silent:
                    silence_s += fs
                    if silence_s >= self._silence_seconds:
                        break
                else:
                    silence_s = 0.0
                if recorded_s >= self._max_seconds:
                    break
            elif elapsed_s >= self._lead_in_seconds:
                break  # no speech onset within the lead-in -> bare wake

            # Fetch the next frame, bounded by the relevant budget.
            if seen_speech:
                timeout = max(self._max_seconds - recorded_s, 0.0)
            else:
                timeout = max(self._lead_in_seconds - elapsed_s, 0.0)
            if timeout <= 0.0:
                break
            try:
                frame = await asyncio.wait_for(self._sub.queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                break

        if not seen_speech:
            log.info("utterance: no speech within %.1fs lead-in (greeting prompt)",
                     self._lead_in_seconds)
            return None
        all_frames = preroll_frames + frames
        preroll_s = len(preroll_frames) * self._bus.frame_ms / 1000
        log.info("utterance: %.2fs speech + %.2fs preroll (%d frames)",
                 recorded_s, preroll_s, len(all_frames))
        return frames_to_wav(all_frames, sr)
