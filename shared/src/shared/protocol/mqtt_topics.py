from typing import Literal

from pydantic import BaseModel

TOPIC_WAKE = "buggsy/events/wake"
TOPIC_SPEAK = "buggsy/cmd/speak"
TOPIC_SPOKE_DONE = "buggsy/events/spoke_done"
TOPIC_MOVE = "buggsy/cmd/move"
TOPIC_UTTERANCE = "buggsy/events/utterance"
TOPIC_STATE = "buggsy/state"


class WakeEvent(BaseModel):
    ts: float
    confidence: float


class SpeakCommand(BaseModel):
    text: str
    audio_b64: str | None = None
    audio_url: str | None = None
    voice_id: str | None = None


class SpokeDoneEvent(BaseModel):
    ts: float


class StateMessage(BaseModel):
    state: Literal["idle", "woken", "speaking", "cooldown"]
    ts: float


class MoveCommand(BaseModel):
    dataset: str
    name: str
    turn_id: str | None = None


class UtteranceEvent(BaseModel):
    """A captured post-wake utterance. Audio is 16-bit mono PCM in a WAV
    container, delivered inline (base64) or by URL for larger clips."""

    ts: float
    audio_b64: str | None = None
    audio_url: str | None = None
    sample_rate: int = 16000
