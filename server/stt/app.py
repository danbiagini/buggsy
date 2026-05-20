"""Minimal faster-whisper STT HTTP service.

POST /transcribe  {"audio_b64": str, "language": optional str}
                  -> {"text": str, "language": str, "segments": [...]}

Audio in: base64-encoded audio bytes (WAV/MP3/etc — PyAV decodes). The
Whisper model loads once at startup, so the first /transcribe is warm.
"""

import base64
import io
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from faster_whisper import WhisperModel
from pydantic import BaseModel

log = logging.getLogger("buggsy.stt")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

MODEL_NAME = os.environ.get("BUGGSY_STT_MODEL", "small.en")
DEVICE = os.environ.get("BUGGSY_STT_DEVICE", "auto")            # auto | cuda | cpu
COMPUTE_TYPE = os.environ.get("BUGGSY_STT_COMPUTE_TYPE", "default")  # default | float16 | int8 | ...

_model: Optional[WhisperModel] = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Warm the model on startup so the first /transcribe is fast. We
    # swallow load failures so the worker still comes up — /health will
    # report loaded=False and the next /transcribe retries.
    try:
        _load_model()
    except Exception as e:
        log.error("model load failed at startup: %s", e)
    yield


app = FastAPI(title="Buggsy STT", lifespan=lifespan)


def _load_model() -> WhisperModel:
    """Lazy-load + cache. Idempotent; raises if the model can't be loaded."""
    global _model
    if _model is not None:
        return _model
    log.info("loading whisper model %s (device=%s compute_type=%s)",
             MODEL_NAME, DEVICE, COMPUTE_TYPE)
    _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
    log.info("whisper model loaded")
    return _model


class TranscribeRequest(BaseModel):
    audio_b64: str
    language: Optional[str] = None  # None -> auto-detect


class TranscribeResponse(BaseModel):
    text: str
    language: str
    segments: list[dict[str, Any]]


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "model": MODEL_NAME, "loaded": _model is not None}


@app.post("/transcribe", response_model=TranscribeResponse)
def transcribe(req: TranscribeRequest) -> TranscribeResponse:
    try:
        audio = base64.b64decode(req.audio_b64, validate=True)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"invalid base64: {e}")
    if not audio:
        raise HTTPException(400, "empty audio")

    model = _load_model()
    segments_gen, info = model.transcribe(
        io.BytesIO(audio),
        language=req.language,
        beam_size=1,        # snappy; large-v3 with beam=5 is for accuracy-tuning later
        vad_filter=True,    # drop silence at edges
    )
    segments = []
    text_chunks = []
    for s in segments_gen:
        segments.append({"start": s.start, "end": s.end, "text": s.text})
        text_chunks.append(s.text)
    text = "".join(text_chunks).strip()

    log.info("transcribe: lang=%s dur=%.2fs text=%r",
             info.language, getattr(info, "duration", -1.0), text[:80])
    return TranscribeResponse(text=text, language=info.language, segments=segments)
