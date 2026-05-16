from typing import Protocol, runtime_checkable

from .mqtt_topics import WakeEvent


@runtime_checkable
class WakeDetector(Protocol):
    def detect(self, frame: bytes) -> WakeEvent | None: ...


@runtime_checkable
class TTS(Protocol):
    async def synthesize(self, text: str, voice_id: str | None = None) -> bytes: ...
