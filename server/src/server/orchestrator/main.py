"""Buggsy orchestrator.

On wake event, asks the planner for tool calls and dispatches them
through the skill framework. v2 starts with `StubPlanner` →
`SaySkill` (functionally equivalent to v1's hardcoded greeting); the
LLM-backed planner lands in #25.

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
import logging
import os
import uuid

import aiomqtt
import httpx

from shared.protocol import (
    TOPIC_SPOKE_DONE,
    TOPIC_STATE,
    TOPIC_WAKE,
    SpokeDoneEvent,
    StateMessage,
    WakeEvent,
    load_config,
)

from .move_catalog import MoveCatalog
from .move_descriptions import load_packaged_descriptions
from .planner import Planner, StubPlanner
from .skills import PlayMoveSkill, SaySkill, SkillContext, SkillRegistry, dispatch

log = logging.getLogger("buggsy.orchestrator")


async def handle_wake(
    client: aiomqtt.Client,
    http: httpx.AsyncClient,
    registry: SkillRegistry,
    planner: Planner,
    payload: bytes,
) -> None:
    try:
        evt = WakeEvent.model_validate_json(payload)
    except Exception as e:
        log.warning("bad wake payload: %s", e)
        return
    turn_id = uuid.uuid4().hex[:8]
    log.info("[turn=%s] wake received: confidence=%.3f ts=%.3f",
             turn_id, evt.confidence, evt.ts)
    calls = await planner.plan()
    ctx = SkillContext(mqtt=client, http=http, turn_id=turn_id)
    await dispatch(calls, registry, ctx)


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
    cfg = load_config()
    host = os.environ.get("BUGGSY_MQTT_HOST", cfg.mqtt.host)
    port = int(os.environ.get("BUGGSY_MQTT_PORT", str(cfg.mqtt.port)))
    tts_url = os.environ.get("BUGGSY_TTS_URL", cfg.tts_service.url)
    voice_id = os.environ.get("BUGGSY_VOICE_ID") or cfg.tts.voice_id

    if cfg.greeting.source != "static":
        log.warning("greeting.source %r not yet implemented — using StubPlanner",
                    cfg.greeting.source)

    planner: Planner = StubPlanner(cfg.greeting.static_phrase)

    log.info("orchestrator config: mqtt=%s:%d tts=%s voice=%s phrase=%r",
             host, port, tts_url, voice_id, cfg.greeting.static_phrase)

    # Merge packaged curated descriptions with user overrides from
    # buggsy.yaml. User config wins on key collisions.
    descriptions = {
        **load_packaged_descriptions(cfg.moves.datasets),
        **cfg.moves.descriptions,
    }
    catalog = MoveCatalog(descriptions=descriptions)
    log.info("move catalog: %d entries", catalog.total_known())

    registry = SkillRegistry([
        SaySkill(tts_url=tts_url, voice_id=voice_id),
        PlayMoveSkill(catalog=catalog),
    ])
    log.info("registered skills: %s", registry.names())

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
                            await handle_wake(client, http, registry, planner, msg.payload)
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
