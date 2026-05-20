import asyncio
import io
import wave

import numpy as np
import pytest

from robot.agent.utterance import (
    PrerollBuffer,
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
    defaults = dict(lead_in_seconds=2.5, max_seconds=8.0,
                    silence_seconds=0.8, silence_rms=400.0)
    defaults.update(kw)
    return UtteranceCapturer(bus, **defaults)


async def test_capture_ends_on_silence():
    # Speech starts immediately (5 loud frames) then 0.8s silence -> stop.
    frames = [_loud_frame()] * 5 + [_silent_frame()] * 20
    bus = _FakeBus(frames)
    cap = _capturer(bus, silence_seconds=0.8)
    wav = await cap.capture()
    assert wav is not None
    with wave.open(io.BytesIO(wav), "rb") as w:
        n_frames = w.getnframes() // FRAME_SAMPLES
    # 5 loud + ~10 silent (0.8s / 0.08s); allow ±1 for float boundary.
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
    # Stops once recorded >= max_seconds; one frame of overshoot at most.
    assert 1.0 <= captured_s <= 1.0 + 0.08 + 1e-6


async def test_no_speech_in_lead_in_returns_none():
    # Bare wake: only silence within the lead-in window -> greeting prompt.
    frames = [_silent_frame()] * 50
    bus = _FakeBus(frames)
    cap = _capturer(bus, lead_in_seconds=0.3)  # ~4 frames
    wav = await cap.capture()
    assert wav is None
    assert bus.unsubscribed == 1


async def test_speech_after_brief_silence_is_captured():
    # A beat of silence, then the user starts talking within the lead-in.
    # Pre-speech silence is not recorded; capture starts at onset.
    frames = [_silent_frame()] * 2 + [_loud_frame()] * 5 + [_silent_frame()] * 20
    bus = _FakeBus(frames)
    cap = _capturer(bus, lead_in_seconds=1.0, silence_seconds=0.8)
    wav = await cap.capture()
    assert wav is not None
    with wave.open(io.BytesIO(wav), "rb") as w:
        n_frames = w.getnframes() // FRAME_SAMPLES
    # 5 loud + ~10 trailing silent; the 2 leading silent frames dropped.
    assert 15 <= n_frames <= 16


async def test_preroll_prepended_on_command():
    # Command detected -> preroll frames are prepended to the WAV.
    frames = [_loud_frame()] * 5 + [_silent_frame()] * 20
    bus = _FakeBus(frames)
    cap = _capturer(bus, silence_seconds=0.8)
    preroll = [_loud_frame()] * 3
    wav = await cap.capture(preroll_frames=preroll)
    assert wav is not None
    with wave.open(io.BytesIO(wav), "rb") as w:
        n_frames = w.getnframes() // FRAME_SAMPLES
    # 3 preroll + (5 loud + ~10 silent) = 18-19
    assert 18 <= n_frames <= 19


async def test_preroll_discarded_on_bare_wake():
    # No speech onset -> bare wake -> None, preroll is NOT emitted.
    frames = [_silent_frame()] * 50
    bus = _FakeBus(frames)
    cap = _capturer(bus, lead_in_seconds=0.3)
    wav = await cap.capture(preroll_frames=[_loud_frame()] * 3)
    assert wav is None


def test_preroll_buffer_maxlen():
    # 1.0s at 80ms frames -> ceil(12.5) = 13 frames retained.
    class _Bus:
        frame_ms = 80
    buf = PrerollBuffer(_Bus(), seconds=1.0)
    assert buf._frames.maxlen == 13
