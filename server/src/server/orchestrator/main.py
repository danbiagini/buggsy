"""Buggsy orchestrator.

On wake event, fetches a greeting text, synthesizes it via the TTS service,
and publishes a SpeakCommand with the inline base64 audio.

Greeting text is hardcoded for now (config comes in #7).

Usage:
    python -m server.orchestrator

Env vars:
    BUGGSY_MQTT_HOST   Broker host. Default: localhost
    BUGGSY_MQTT_PORT   Broker port. Default: 1883
    BUGGSY_TTS_URL     TTS service base URL. Default: http://localhost:8001
    BUGGSY_VOICE_ID    Voice to request from TTS. Default: (server default)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os

import aiomqtt
import httpx

from shared.protocol import (
    TOPIC_SPEAK,
    TOPIC_SPOKE_DONE,
    TOPIC_STATE,
    TOPIC_WAKE,
    SpeakCommand,
    SpokeDoneEvent,
    StateMessage,
    WakeEvent,
)

log = logging.getLogger("buggsy.orchestrator")

GREETING_TEXT = "Hi Dan, what can I help with?"
TTS_TIMEOUT_S = 15.0


async def synthesize(http: httpx.AsyncClient, tts_url: str, text: str, voice_id: str | None) -> bytes:
    payload: dict[str, str | None] = {"text": text}
    if voice_id:
        payload["voice_id"] = voice_id
    r = await http.post(f"{tts_url}/synthesize", json=payload, timeout=TTS_TIMEOUT_S)
    r.raise_for_status()
    return r.content


async def handle_wake(
    client: aiomqtt.Client,
    http: httpx.AsyncClient,
    tts_url: str,
    voice_id: str | None,
    payload: bytes,
) -> None:
    try:
        evt = WakeEvent.model_validate_json(payload)
    except Exception as e:
        log.warning("bad wake payload: %s", e)
        return
    log.info("wake received: confidence=%.3f ts=%.3f", evt.confidence, evt.ts)
    text = GREETING_TEXT
    try:
        audio = await synthesize(http, tts_url, text, voice_id)
    except (httpx.HTTPError, OSError) as e:
        log.error("TTS request failed: %s — sending speak with no audio", e)
        audio = b""
    cmd = SpeakCommand(
        text=text,
        audio_b64=base64.b64encode(audio).decode("ascii") if audio else None,
        voice_id=voice_id,
    )
    await client.publish(TOPIC_SPEAK, cmd.model_dump_json())
    log.info("published speak: %d bytes audio", len(audio))


async def handle_state(payload: bytes) -> None:
    try:
        msg = StateMessage.model_validate_json(payload)
    except Exception as e:
        log.warning("bad state payload: %s", e)
        return
    log.info("robot state: %s (ts=%.1f)", msg.state, msg.ts)


async def handle_spoke_done(payload: bytes) -> None:
    try:
        evt = SpokeDoneEvent.model_validate_json(payload)
    except Exception as e:
        log.warning("bad spoke_done payload: %s", e)
        return
    log.info("robot finished speaking (ts=%.1f)", evt.ts)


async def serve() -> None:
    host = os.environ.get("BUGGSY_MQTT_HOST", "localhost")
    port = int(os.environ.get("BUGGSY_MQTT_PORT", "1883"))
    tts_url = os.environ.get("BUGGSY_TTS_URL", "http://localhost:8001")
    voice_id = os.environ.get("BUGGSY_VOICE_ID") or None
    log.info("orchestrator config: mqtt=%s:%d tts=%s voice=%s", host, port, tts_url, voice_id)

    async with httpx.AsyncClient() as http:
        while True:
            try:
                async with aiomqtt.Client(host, port=port) as client:
                    log.info("mqtt connected")
                    await client.subscribe(TOPIC_WAKE)
                    await client.subscribe(TOPIC_STATE)
                    await client.subscribe(TOPIC_SPOKE_DONE)
                    async for msg in client.messages:
                        topic = msg.topic.value
                        if topic == TOPIC_WAKE:
                            await handle_wake(client, http, tts_url, voice_id, msg.payload)
                        elif topic == TOPIC_STATE:
                            await handle_state(msg.payload)
                        elif topic == TOPIC_SPOKE_DONE:
                            await handle_spoke_done(msg.payload)
            except aiomqtt.MqttError as e:
                log.warning("mqtt connection lost: %s — reconnecting in 5s", e)
                await asyncio.sleep(5)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
