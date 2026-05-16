"""Buggsy orchestrator — v1 dummy.

Subscribes to wake events, logs them, and replies with a placeholder speak
command. TTS comes online in #6.

Usage:
    python -m server.orchestrator

Env vars:
    BUGGSY_MQTT_HOST  Broker host. Default: localhost
    BUGGSY_MQTT_PORT  Broker port. Default: 1883
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import aiomqtt

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

PLACEHOLDER_GREETING = "(placeholder greeting — TTS arrives in #6)"


async def handle_wake(client: aiomqtt.Client, payload: bytes) -> None:
    try:
        evt = WakeEvent.model_validate_json(payload)
    except Exception as e:
        log.warning("bad wake payload: %s", e)
        return
    log.info("wake received: confidence=%.3f ts=%.3f", evt.confidence, evt.ts)
    cmd = SpeakCommand(text=PLACEHOLDER_GREETING)
    await client.publish(TOPIC_SPEAK, cmd.model_dump_json())
    log.info("published placeholder speak command")


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
    log.info("connecting to mqtt://%s:%d", host, port)

    while True:
        try:
            async with aiomqtt.Client(host, port=port) as client:
                log.info("connected")
                await client.subscribe(TOPIC_WAKE)
                await client.subscribe(TOPIC_STATE)
                await client.subscribe(TOPIC_SPOKE_DONE)
                async for msg in client.messages:
                    topic = msg.topic.value
                    if topic == TOPIC_WAKE:
                        await handle_wake(client, msg.payload)
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
