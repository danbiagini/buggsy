"""Microphone capture with async pub-sub fan-out.

Producer is sounddevice's PortAudio callback (runs in its own thread). Each
subscriber gets a bounded queue; if a consumer falls behind the frame is
dropped for that subscriber only — the producer is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 16_000
DEFAULT_FRAME_MS = 80
DEFAULT_CHANNELS = 1


@dataclass
class Subscription:
    queue: asyncio.Queue[bytes]
    dropped: int = 0
    _closed: bool = field(default=False)

    async def frames(self) -> AsyncIterator[bytes]:
        while not self._closed:
            yield await self.queue.get()

    def close(self) -> None:
        self._closed = True


class AudioBus:
    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        frame_ms: int = DEFAULT_FRAME_MS,
        channels: int = DEFAULT_CHANNELS,
        device: int | str | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.channels = channels
        self.device = device
        self.frame_samples = sample_rate * frame_ms // 1000
        self._stream: sd.InputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: list[Subscription] = []

    def subscribe(self, max_queue: int = 10) -> Subscription:
        sub = Subscription(queue=asyncio.Queue(maxsize=max_queue))
        self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        """Remove a subscription so the producer stops dispatching to it.
        Safe to call more than once."""
        sub.close()
        try:
            self._subs.remove(sub)
        except ValueError:
            pass

    def start(self) -> None:
        if self._stream is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.frame_samples,
            device=self.device,
            callback=self._on_audio,
        )
        self._stream.start()
        log.info(
            "AudioBus started: %d Hz, %d ms frames (%d samples), device=%s",
            self.sample_rate, self.frame_ms, self.frame_samples, self.device,
        )

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None
        for sub in self._subs:
            sub.close()
        log.info("AudioBus stopped")

    def _on_audio(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            log.debug("PortAudio status: %s", status)
        # indata shape: (frames, channels). For mono it's still 2D — flatten to bytes.
        payload = indata.tobytes()
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._dispatch, payload)

    def _dispatch(self, payload: bytes) -> None:
        for sub in self._subs:
            try:
                sub.queue.put_nowait(payload)
            except asyncio.QueueFull:
                sub.dropped += 1
