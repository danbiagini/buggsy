import base64
import json

import httpx

from server.orchestrator.skills import SayParams, SaySkill, SkillContext


class _FakeMqtt:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, topic, payload, **kwargs):
        self.published.append((topic, payload))


async def test_say_publishes_speak_with_audio():
    audio_bytes = b"WAVE-DATA"
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=audio_bytes))
    async with httpx.AsyncClient(transport=transport) as http:
        mqtt = _FakeMqtt()
        skill = SaySkill(tts_url="http://tts.test", voice_id="amy")
        ctx = SkillContext(mqtt=mqtt, http=http, turn_id="t-1")  # type: ignore[arg-type]
        result = await skill.run(SayParams(text="hello"), ctx)
    assert result.ok
    assert len(mqtt.published) == 1
    topic, payload = mqtt.published[0]
    assert topic == "buggsy/cmd/speak"
    cmd = json.loads(payload)
    assert cmd["text"] == "hello"
    assert cmd["voice_id"] == "amy"
    assert base64.b64decode(cmd["audio_b64"]) == audio_bytes


async def test_say_publishes_no_audio_when_tts_fails():
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        mqtt = _FakeMqtt()
        skill = SaySkill(tts_url="http://tts.test", voice_id=None)
        ctx = SkillContext(mqtt=mqtt, http=http, turn_id="t-2")  # type: ignore[arg-type]
        result = await skill.run(SayParams(text="hello"), ctx)
    assert result.ok  # still ok — speak published with text but no audio
    cmd = json.loads(mqtt.published[0][1])
    assert cmd["text"] == "hello"
    assert cmd["audio_b64"] is None


async def test_say_omits_voice_id_in_tts_payload_when_none():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, content=b"x")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        mqtt = _FakeMqtt()
        skill = SaySkill(tts_url="http://tts.test", voice_id=None)
        ctx = SkillContext(mqtt=mqtt, http=http, turn_id="t-3")  # type: ignore[arg-type]
        await skill.run(SayParams(text="hi"), ctx)
    assert captured["body"] == {"text": "hi"}
