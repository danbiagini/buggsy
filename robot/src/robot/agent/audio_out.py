"""WAV playback over sounddevice for the Buggsy speak pipeline.

Decodes a base64-encoded WAV blob received in a SpeakCommand and plays it
on the configured output device. Blocking; call via run_in_executor from
async code.
"""

from __future__ import annotations

import base64
import io
import logging
import wave

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

REACHY_OUTPUT_NAME_HINT = "Reachy Mini Audio"


def pick_output_device(env_value: str | None) -> int | str | None:
    """Same auto-detect strategy as the input side."""
    if env_value:
        return int(env_value) if env_value.isdigit() else env_value
    try:
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0 and REACHY_OUTPUT_NAME_HINT in d["name"]:
                log.info("auto-selected output device [%d] %s", i, d["name"])
                return i
    except Exception as e:
        log.warning("output device auto-detect failed: %s", e)
    return None


def _decode_wav(audio_bytes: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
        sr = wav.getframerate()
        n_channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        raw = wav.readframes(wav.getnframes())
    if sampwidth == 2:
        data = np.frombuffer(raw, dtype=np.int16)
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype=np.int32)
    elif sampwidth == 1:
        data = np.frombuffer(raw, dtype=np.uint8)
    else:
        raise ValueError(f"unsupported sample width: {sampwidth}")
    if n_channels > 1:
        data = data.reshape(-1, n_channels)
    return data, sr


def play_wav_b64(audio_b64: str, device: int | str | None = None) -> None:
    audio_bytes = base64.b64decode(audio_b64)
    data, sr = _decode_wav(audio_bytes)
    log.info("audio_out: playing %d frames at %d Hz (device=%s)", len(data), sr, device)
    sd.play(data, samplerate=sr, device=device, blocking=True)
