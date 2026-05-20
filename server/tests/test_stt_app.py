"""Endpoint smoke tests for the STT service.

faster-whisper is a heavy dep; we stub it via sys.modules before
importing the app so these tests run anywhere. The goal here is to
catch route/payload/error-handling regressions, not Whisper-quality
issues (those need real audio + GPU and live in a separate manual
checklist on the PR).
"""

from __future__ import annotations

import base64
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ── Stub `faster_whisper` ───────────────────────────────────────────


class _FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class _FakeWhisperModel:
    """Records the last audio bytes received, returns canned segments."""

    last_audio: bytes | None = None
    last_language: str | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    def transcribe(self, audio_io, language=None, beam_size=1, vad_filter=True):
        _FakeWhisperModel.last_audio = audio_io.read()
        _FakeWhisperModel.last_language = language
        info = SimpleNamespace(language=language or "en", duration=2.0)
        return iter([_FakeSegment(0.0, 1.0, "hello"),
                     _FakeSegment(1.0, 2.0, " world")]), info


_fake = ModuleType("faster_whisper")
_fake.WhisperModel = _FakeWhisperModel  # type: ignore[attr-defined]
sys.modules["faster_whisper"] = _fake


# ── Load server/stt/app.py without making `stt` a real subpackage ──

_STT_PATH = Path(__file__).resolve().parents[1] / "stt" / "app.py"
_spec = importlib.util.spec_from_file_location("buggsy_stt_app", str(_STT_PATH))
assert _spec is not None and _spec.loader is not None
stt_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stt_app)

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(stt_app.app)


# ── Tests ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_fake():
    _FakeWhisperModel.last_audio = None
    _FakeWhisperModel.last_language = None
    yield


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "model" in body


def test_transcribe_happy_path():
    payload = {"audio_b64": base64.b64encode(b"fake-wav-data").decode()}
    r = client.post("/transcribe", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "hello world"
    assert body["language"] == "en"
    assert len(body["segments"]) == 2
    assert body["segments"][0]["text"] == "hello"
    # The stub recorded what the app actually passed in.
    assert _FakeWhisperModel.last_audio == b"fake-wav-data"


def test_transcribe_with_explicit_language():
    payload = {
        "audio_b64": base64.b64encode(b"fake").decode(),
        "language": "fr",
    }
    r = client.post("/transcribe", json=payload)
    assert r.status_code == 200
    assert r.json()["language"] == "fr"
    assert _FakeWhisperModel.last_language == "fr"


def test_transcribe_invalid_base64():
    r = client.post("/transcribe", json={"audio_b64": "not!!!base64"})
    assert r.status_code == 400
    assert "invalid base64" in r.json()["detail"]


def test_transcribe_empty_audio_rejected():
    r = client.post("/transcribe", json={"audio_b64": ""})
    assert r.status_code == 400


def test_transcribe_missing_field_rejected():
    r = client.post("/transcribe", json={})
    # FastAPI / pydantic validation -> 422
    assert r.status_code == 422
