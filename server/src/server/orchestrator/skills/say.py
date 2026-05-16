"""SaySkill: speak text out loud via the TTS service.

Wraps the TTS HTTP call + `buggsy/cmd/speak` publish flow that used to
live inline in `handle_wake`. First skill in the v2 framework; exercises
the dispatcher on every interaction.
"""

from __future__ import annotations

import base64
import logging

import httpx
from pydantic import BaseModel, Field

from shared.protocol import TOPIC_SPEAK, SpeakCommand

from .base import SkillContext, SkillResult

log = logging.getLogger(__name__)

TTS_TIMEOUT_S = 15.0


class SayParams(BaseModel):
    text: str = Field(
        ...,
        description="Text for the robot to speak. Keep concise — at most two short sentences.",
        min_length=1,
        max_length=500,
    )


class SaySkill:
    name = "say"
    description = "Speak text out loud through the robot's speaker."
    Params = SayParams

    def __init__(self, tts_url: str, voice_id: str | None) -> None:
        self._tts_url = tts_url
        self._voice_id = voice_id

    async def run(self, params: SayParams, ctx: SkillContext) -> SkillResult:
        try:
            audio = await self._synthesize(ctx.http, params.text)
        except (httpx.HTTPError, OSError) as e:
            log.error(
                "[turn=%s] TTS failed: %s — publishing speak with no audio",
                ctx.turn_id, e,
            )
            audio = b""
        cmd = SpeakCommand(
            text=params.text,
            audio_b64=base64.b64encode(audio).decode("ascii") if audio else None,
            voice_id=self._voice_id,
        )
        await ctx.mqtt.publish(TOPIC_SPEAK, cmd.model_dump_json())
        log.info("[turn=%s] say: %r (%dB audio)", ctx.turn_id, params.text, len(audio))
        return SkillResult(ok=True, skill=self.name, detail=f"{len(audio)}B audio")

    async def _synthesize(self, http: httpx.AsyncClient, text: str) -> bytes:
        payload: dict[str, str | None] = {"text": text}
        if self._voice_id:
            payload["voice_id"] = self._voice_id
        r = await http.post(f"{self._tts_url}/synthesize", json=payload, timeout=TTS_TIMEOUT_S)
        r.raise_for_status()
        return r.content
