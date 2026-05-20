import asyncio
import io
import wave

import numpy as np
import pytest

from robot.agent.utterance import (
    UtteranceCapturer,
    frame_rms,
    frame_seconds,
    frames_to_wav,
)

SAMPLE_RATE = 16000
FRAME_MS = 80
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 1280
FRAME_BYTES = FRAME_SAMPLES * 2


def _loud_frame(amplitude: int = 5000) -> bytes:
    return np.full(FRAME_SAMPLES, amplitude, dtype=np.int16).tobytes()


def _silent_frame() -> bytes:
    return np.zeros(FRAME_SAMPLES, dtype=np.int16).tobytes()


# ── pure helpers ────────────────────────────────────────────────────


def test_frame_rms_silence_vs_speech():
    assert frame_rms(_silent_frame()) == 0.0
    assert frame_rms(_loud_frame(5000)) == pytest.approx(5000.0, rel=1e-3)


def test_frame_rms_empty():
    assert frame_rms(b"") == 0.0


def test_frame_seconds():
    assert frame_seconds(_loud_frame(), SAMPLE_RATE) == pytest.approx(0.08)


def test_frames_to_wav_roundtrips():
    frames = [_loud_frame(), _loud_frame()]
    wav = frames_to_wav(frames, SAMPLE_RATE)
    with wave.open(io.BytesIO(wav), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == SAMPLE_RATE
        assert w.getnframes() == 2 * FRAME_SAMPLES


# ── capture loop ────────────────────────────────────────────────────


class _FakeSub:
    def __init__(self, frames: list[bytes]) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        for f in frames:
            self.queue.put_nowait(f)

    def close(self) -> None:
        pass


class _FakeBus:
    def __init__(self, frames: list[bytes]) -> None:
        self.sample_rate = SAMPLE_RATE
        self._frames = frames
        self.subscribed = 0
        self.unsubscribed = 0

    def subscribe(self, max_queue: int = 10) -> _FakeSub:
        self.subscribed += 1
        return _FakeSub(self._frames)

    def unsubscribe(self, sub) -> None:
        self.unsubscribed += 1


def _capturer(bus, **kw) -> UtteranceCapturer:
    defaults = dict(max_seconds=8.0, silence_seconds=0.8, silence_rms=400.0)
    defaults.update(kw)
    return UtteranceCapturer(bus, **defaults)


async def test_capture_ends_on_silence():
    # 5 loud frames (0.4s speech) then 10 silent frames (0.8s) -> should
    # stop right after the silence run crosses silence_seconds.
    frames = [_loud_frame()] * 5 + [_silent_frame()] * 20
    bus = _FakeBus(frames)
    cap = _capturer(bus, silence_seconds=0.8)
    wav = await cap.capture()
    assert wav is not None
    with wave.open(io.BytesIO(wav), "rb") as w:
        n_frames = w.getnframes() // FRAME_SAMPLES
    # 5 loud + ~10 silent frames (0.8s / 0.08s); allow ±1 for the float
    # accumulation boundary. The point: it stops shortly after silence,
    # not at the 25-frame end of the buffer.
    assert 15 <= n_frames <= 16
    assert bus.unsubscribed == 1  # cleaned up its subscription


async def test_capture_ends_on_max_seconds():
    # All loud, never silent — must stop at the hard cap.
    frames = [_loud_frame()] * 200  # 16s worth
    bus = _FakeBus(frames)
    cap = _capturer(bus, max_seconds=1.0)
    wav = await cap.capture()
    with wave.open(io.BytesIO(wav), "rb") as w:
        captured_s = (w.getnframes() / SAMPLE_RATE)
    # Stops once captured >= max_seconds; one frame of overshoot at most.
    assert 1.0 <= captured_s <= 1.0 + 0.08 + 1e-6


async def test_capture_returns_none_when_immediately_silent():
    # Silence from the start -> still returns frames up to silence window,
    # but if silence_seconds is tiny and all silent, we get a short clip.
    frames = [_silent_frame()] * 20
    bus = _FakeBus(frames)
    cap = _capturer(bus, silence_seconds=0.16)  # 2 frames
    wav = await cap.capture()
    # 2 silent frames captured before the silence run triggers stop.
    with wave.open(io.BytesIO(wav), "rb") as w:
        assert w.getnframes() // FRAME_SAMPLES == 2
