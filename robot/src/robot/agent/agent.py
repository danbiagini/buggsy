"""Buggsy agent: wake detection drives a motion state machine + MQTT bus.

State machine:
    idle    -> wake event -> woken (attentive_pose)
    woken   -> cooldown_s of no further wake -> idle (resting_pose)

MQTT:
    publishes  buggsy/events/wake        on each wake detection
    publishes  buggsy/state (retained)   every 10s (heartbeat)
    subscribes buggsy/cmd/speak          logs received commands

Fake wake (dev): send SIGUSR1 to the process.
    kill -USR1 $(pgrep -f robot.agent.agent)

Usage:
    /venvs/apps_venv/bin/python -m robot.agent.agent
    BUGGSY_MOCK_MOTION=1 python -m robot.agent.agent     # dev mac, no robot
    BUGGSY_SKIP_MQTT=1   python -m robot.agent.agent     # standalone, no broker

Env vars:
    BUGGSY_WAKE_MODEL       Path to openWakeWord .onnx model.
    BUGGSY_WAKE_THRESHOLD   Wake confidence cutoff. Default: 0.5
    BUGGSY_COOLDOWN_S       Seconds to stay attentive after last wake. Default: 5.0
    BUGGSY_MOCK_MOTION      Set to 1 to skip the Reachy SDK (no real robot needed).
    BUGGSY_AUDIO_DEVICE     sounddevice input device index or name.
    BUGGSY_DAEMON_URL       Reachy daemon base URL. Default: http://localhost:8000
    BUGGSY_SKIP_DAEMON_WAKE Set to 1 to skip the wake/sleep daemon calls.
    BUGGSY_MQTT_HOST        Broker host. Default: localhost
    BUGGSY_MQTT_PORT        Broker port. Default: 1883
    BUGGSY_SKIP_MQTT        Set to 1 to run without MQTT (no remote events).
    BUGGSY_AUDIO_OUTPUT_DEVICE  sounddevice output device. Auto-detects Reachy speaker.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager, contextmanager
from enum import Enum

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
    load_config,
)

from .audio_bus import AudioBus
from .audio_out import pick_output_device, play_wav_b64
from .motion import MockMotion, Motion, MotionLike
from .wake_detector import OpenWakeWordDetector, run_wake_detection

log = logging.getLogger("buggsy.agent")

DEFAULT_DAEMON_URL = "http://localhost:8000"
DEFAULT_MQTT_HOST = "localhost"
DEFAULT_MQTT_PORT = 1883
HEARTBEAT_S = 10.0
WAKE_SETTLE_S = 3.0
REACHY_MIC_NAME_HINT = "Reachy Mini Audio"


def _pick_audio_device(env_value: str | None) -> int | str | None:
    if env_value:
        return int(env_value) if env_value.isdigit() else env_value
    try:
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and REACHY_MIC_NAME_HINT in d["name"]:
                log.info("auto-selected audio device [%d] %s", i, d["name"])
                return i
    except Exception as e:
        log.warning("audio device auto-detect failed: %s", e)
    return None


def _daemon_post(url: str, path: str, timeout: float = 5.0) -> None:
    req = urllib.request.Request(f"{url}{path}", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def daemon_wake_up(url: str) -> None:
    log.info("daemon: wake_up")
    _daemon_post(url, "/api/move/play/wake_up")
    time.sleep(WAKE_SETTLE_S)


def daemon_goto_sleep(url: str) -> None:
    log.info("daemon: goto_sleep")
    try:
        _daemon_post(url, "/api/move/play/goto_sleep")
    except (urllib.error.URLError, OSError) as e:
        log.warning("daemon goto_sleep failed: %s", e)


class State(Enum):
    IDLE = "idle"
    WOKEN = "woken"


@contextmanager
def open_mini(use_mock: bool):
    if use_mock:
        yield None
        return
    from reachy_mini import ReachyMini

    with ReachyMini(media_backend="no_media") as mini:
        yield mini


@asynccontextmanager
async def maybe_mqtt(host: str, port: int, skip: bool):
    if skip:
        log.info("MQTT disabled (BUGGSY_SKIP_MQTT=1)")
        yield None
        return
    log.info("mqtt connect: %s:%d", host, port)
    try:
        async with aiomqtt.Client(host, port=port) as client:
            log.info("mqtt connected")
            yield client
    except aiomqtt.MqttError as e:
        log.error("mqtt connect failed: %s — set BUGGSY_SKIP_MQTT=1 to run standalone", e)
        raise


async def _publish_safe(client: aiomqtt.Client | None, topic: str, payload: str, **kwargs) -> None:
    if client is None:
        return
    try:
        await client.publish(topic, payload, **kwargs)
    except aiomqtt.MqttError as e:
        log.warning("publish %s failed: %s", topic, e)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = load_config()
    model_path = os.environ.get("BUGGSY_WAKE_MODEL", cfg.wake.model_path)
    threshold = float(os.environ.get("BUGGSY_WAKE_THRESHOLD", str(cfg.wake.threshold)))
    cooldown_s = float(os.environ.get("BUGGSY_COOLDOWN_S", str(cfg.motion.cooldown_seconds)))
    use_mock = os.environ.get("BUGGSY_MOCK_MOTION") == "1"
    daemon_url = os.environ.get("BUGGSY_DAEMON_URL", DEFAULT_DAEMON_URL)
    skip_daemon_wake = os.environ.get("BUGGSY_SKIP_DAEMON_WAKE") == "1"
    mqtt_host = os.environ.get("BUGGSY_MQTT_HOST", DEFAULT_MQTT_HOST)
    mqtt_port = int(os.environ.get("BUGGSY_MQTT_PORT", str(DEFAULT_MQTT_PORT)))
    skip_mqtt = os.environ.get("BUGGSY_SKIP_MQTT") == "1"
    device = _pick_audio_device(os.environ.get("BUGGSY_AUDIO_DEVICE"))
    output_device = pick_output_device(os.environ.get("BUGGSY_AUDIO_OUTPUT_DEVICE"))

    state = State.IDLE
    last_wake_ts = 0.0

    if not use_mock and not skip_daemon_wake:
        daemon_wake_up(daemon_url)

    with open_mini(use_mock) as mini:
        motion: MotionLike = MockMotion() if use_mock else Motion(mini)
        motion.resting_pose()

        bus = AudioBus(device=device)
        bus.start()
        detector = OpenWakeWordDetector(model_path=model_path, threshold=threshold)

        async with maybe_mqtt(mqtt_host, mqtt_port, skip_mqtt) as mqtt:

            async def go_attentive(evt: WakeEvent) -> None:
                nonlocal state, last_wake_ts
                last_wake_ts = evt.ts
                if state == State.IDLE:
                    state = State.WOKEN
                    log.info("WAKE confidence=%.3f -> attentive", evt.confidence)
                    motion.attentive_pose()
                else:
                    log.info("WAKE (already attentive) confidence=%.3f", evt.confidence)
                # Fire-and-forget the MQTT publish so motion isn't gated on broker.
                asyncio.create_task(_publish_safe(mqtt, TOPIC_WAKE, evt.model_dump_json()))

            async def cooldown_watcher() -> None:
                nonlocal state
                while True:
                    await asyncio.sleep(0.5)
                    if state == State.WOKEN and (time.time() - last_wake_ts) > cooldown_s:
                        state = State.IDLE
                        log.info("cooldown elapsed -> resting")
                        motion.resting_pose()

            async def heartbeat() -> None:
                while True:
                    msg = StateMessage(state=state.value, ts=time.time())
                    await _publish_safe(mqtt, TOPIC_STATE, msg.model_dump_json(), retain=True)
                    await asyncio.sleep(HEARTBEAT_S)

            async def speak_listener() -> None:
                if mqtt is None:
                    return
                await mqtt.subscribe(TOPIC_SPEAK)
                async for msg in mqtt.messages:
                    if msg.topic.value != TOPIC_SPEAK:
                        continue
                    try:
                        cmd = SpeakCommand.model_validate_json(msg.payload)
                    except Exception as e:
                        log.warning("bad speak command: %s", e)
                        continue
                    log.info("SPEAK received: text=%r voice_id=%r audio=%s",
                             cmd.text, cmd.voice_id,
                             "inline" if cmd.audio_b64 else (cmd.audio_url or "none"))
                    if not cmd.audio_b64:
                        log.warning("speak with no inline audio — skipping playback")
                        continue
                    try:
                        await asyncio.get_running_loop().run_in_executor(
                            None, play_wav_b64, cmd.audio_b64, output_device
                        )
                    except Exception as e:
                        log.warning("playback failed: %s", e)
                    asyncio.create_task(_publish_safe(
                        mqtt, TOPIC_SPOKE_DONE,
                        SpokeDoneEvent(ts=time.time()).model_dump_json(),
                    ))

            loop = asyncio.get_running_loop()

            def fire_fake_wake() -> None:
                log.info("SIGUSR1 -> fake wake")
                loop.create_task(go_attentive(WakeEvent(ts=time.time(), confidence=1.0)))

            loop.add_signal_handler(signal.SIGUSR1, fire_fake_wake)

            tasks = [
                asyncio.create_task(cooldown_watcher(), name="cooldown"),
                asyncio.create_task(heartbeat(), name="heartbeat"),
                asyncio.create_task(speak_listener(), name="speak_listener"),
            ]
            log.info("agent ready (mock_motion=%s, mqtt=%s, cooldown=%.1fs)",
                     use_mock, mqtt is not None, cooldown_s)
            try:
                await run_wake_detection(bus, detector, go_attentive)
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                bus.stop()
                try:
                    motion.resting_pose()
                except Exception:
                    pass
                if not use_mock and not skip_daemon_wake:
                    daemon_goto_sleep(daemon_url)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
