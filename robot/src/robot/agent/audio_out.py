"""WAV playback over sounddevice for the Buggsy speak pipeline.

Decodes a base64-encoded WAV blob, resamples to the output device's native
sample rate if needed (the Reachy USB audio is fixed at 16kHz; Piper TTS
typically produces 22050Hz), and plays it. Blocking; call via run_in_executor
from async code.
"""

from __future__ import annotations

import base64
import io
import logging
import wave
from math import gcd

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

log = logging.getLogger(__name__)

REACHY_OUTPUT_NAME_HINT = "reachymini_audio_sink"


def pick_output_device(env_value: str | None) -> int | str | None:
    """Auto-detect the Reachy speaker sink in pipewire.

    The pipewire alias for the Reachy speaker is `reachymini_audio_sink`.
    sounddevice does substring matching on names.
    """
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


def _resample(data: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    g = gcd(src_sr, dst_sr)
    up = dst_sr // g
    down = src_sr // g
    if data.ndim == 1:
        return resample_poly(data, up, down).astype(data.dtype)
    cols = [resample_poly(data[:, c], up, down).astype(data.dtype) for c in range(data.shape[1])]
    return np.column_stack(cols)


def _device_samplerate(device: int | str | None) -> int | None:
    if device is None:
        return None
    try:
        info = sd.query_devices(device, "output")
        return int(info["default_samplerate"])
    except Exception as e:
        log.debug("could not query device samplerate: %s", e)
        return None


def play_wav_b64(audio_b64: str, device: int | str | None = None) -> None:
    audio_bytes = base64.b64decode(audio_b64)
    data, sr = _decode_wav(audio_bytes)

    target_sr = _device_samplerate(device)
    if target_sr and target_sr != sr:
        log.info("audio_out: resampling %d Hz -> %d Hz", sr, target_sr)
        data = _resample(data, sr, target_sr)
        sr = target_sr

    log.info("audio_out: playing %d frames at %d Hz (device=%s)", len(data), sr, device)
    sd.play(data, samplerate=sr, device=device, blocking=True)
