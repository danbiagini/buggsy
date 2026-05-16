"""Minimal Piper TTS HTTP service.

POST /synthesize  {"text": str, "voice_id": optional str} -> audio/wav

Voices live under $BUGGSY_TTS_VOICES_DIR (default /voices). Voice files
are <voice_id>.onnx with sibling <voice_id>.onnx.json. The default voice
($BUGGSY_TTS_DEFAULT_VOICE) is baked into the image at build time.
"""

from __future__ import annotations

import io
import logging
import os
import wave
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from piper.voice import PiperVoice
from pydantic import BaseModel

log = logging.getLogger("buggsy.tts")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

VOICES_DIR = Path(os.environ.get("BUGGSY_TTS_VOICES_DIR", "/voices"))
DEFAULT_VOICE = os.environ.get("BUGGSY_TTS_DEFAULT_VOICE", "en_US-amy-medium")

app = FastAPI(title="Buggsy TTS")
_voices: dict[str, PiperVoice] = {}


def _load_voice(voice_id: str) -> PiperVoice:
    if voice_id in _voices:
        return _voices[voice_id]
    onnx = VOICES_DIR / f"{voice_id}.onnx"
    if not onnx.is_file():
        raise HTTPException(status_code=404, detail=f"voice '{voice_id}' not found at {onnx}")
    log.info("loading voice %s", voice_id)
    _voices[voice_id] = PiperVoice.load(str(onnx))
    return _voices[voice_id]


class SynthesizeRequest(BaseModel):
    text: str
    voice_id: str | None = None


@app.on_event("startup")
def warm_default_voice() -> None:
    try:
        _load_voice(DEFAULT_VOICE)
    except HTTPException as e:
        log.error("could not warm default voice %s: %s", DEFAULT_VOICE, e.detail)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "default_voice": DEFAULT_VOICE}


@app.post("/synthesize")
def synthesize(req: SynthesizeRequest) -> Response:
    voice_id = req.voice_id or DEFAULT_VOICE
    voice = _load_voice(voice_id)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        voice.synthesize_wav(req.text, wav)
    audio = buf.getvalue()
    log.info("synth voice=%s len=%dB text=%r", voice_id, len(audio), req.text[:60])
    return Response(content=audio, media_type="audio/wav")
