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
import base64
import json
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
    TOPIC_MOVE,
    TOPIC_SPEAK,
    TOPIC_SPOKE_DONE,
    TOPIC_STATE,
    TOPIC_UTTERANCE,
    TOPIC_WAKE,
    MoveCommand,
    SpeakCommand,
    SpokeDoneEvent,
    StateMessage,
    UtteranceEvent,
    WakeEvent,
    load_config,
)

from .audio_bus import AudioBus
from .audio_out import pick_output_device, play_wav_b64
from .motion import MockMotion, Motion, MotionLike
from .utterance import PrerollBuffer, UtteranceCapturer
from .wake_detector import OpenWakeWordDetector, run_wake_detection

log = logging.getLogger("buggsy.agent")

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


def daemon_play_recorded_move(
    url: str, dataset: str, name: str, timeout: float = 5.0,
) -> str | None:
    """POST a recorded-move play to the daemon.

    Returns the move UUID from the daemon's JSON response on success, or
    None on HTTP / network error / unparseable body. Never raises — the
    move listener treats failure as "log and move on."
    """
    path = f"/api/move/play/recorded-move-dataset/{dataset}/{name}"
    req = urllib.request.Request(f"{url}{path}", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        log.warning("daemon move %s/%s -> HTTP %d", dataset, name, e.code)
        return None
    except (urllib.error.URLError, OSError) as e:
        log.warning("daemon move %s/%s -> %s", dataset, name, e)
        return None
    try:
        return json.loads(body).get("uuid")
    except (ValueError, AttributeError, TypeError):
        log.debug("daemon move %s/%s returned non-JSON body", dataset, name)
        return None


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
    daemon_url = os.environ.get("BUGGSY_DAEMON_URL", cfg.daemon.url)
    skip_daemon_wake = os.environ.get("BUGGSY_SKIP_DAEMON_WAKE") == "1"
    mqtt_host = os.environ.get("BUGGSY_MQTT_HOST", cfg.mqtt.host)
    mqtt_port = int(os.environ.get("BUGGSY_MQTT_PORT", str(cfg.mqtt.port)))
    skip_mqtt = os.environ.get("BUGGSY_SKIP_MQTT") == "1"
    # Audio device resolution: env var > config file > auto-detect
    input_env = os.environ.get("BUGGSY_AUDIO_DEVICE") or (
        str(cfg.audio.input_device) if cfg.audio.input_device is not None else None
    )
    output_env = os.environ.get("BUGGSY_AUDIO_OUTPUT_DEVICE") or (
        str(cfg.audio.output_device) if cfg.audio.output_device is not None else None
    )
    device = _pick_audio_device(input_env)
    output_device = pick_output_device(output_env)
    output_volume = cfg.audio.output_volume

    state = State.IDLE
    last_wake_ts = 0.0
    capture_task: asyncio.Task | None = None

    with open_mini(use_mock) as mini:
        motion: MotionLike = (
            MockMotion() if use_mock else Motion(mini, cfg.motion.attentive, cfg.motion.resting)
        )
        motion.resting_pose()

        bus = AudioBus(device=device)
        bus.start()
        detector = OpenWakeWordDetector(
            model_path=model_path,
            threshold=threshold,
            vad_threshold=cfg.wake.vad_threshold,
            enable_speex_noise_suppression=cfg.wake.enable_speex_noise_suppression,
        )
        capturer = UtteranceCapturer(
            bus,
            lead_in_seconds=cfg.utterance.lead_in_seconds,
            max_seconds=cfg.utterance.max_seconds,
            silence_seconds=cfg.utterance.silence_seconds,
            silence_rms=cfg.utterance.silence_rms,
        )
        preroll = PrerollBuffer(bus, cfg.utterance.preroll_seconds)
        preroll.start()

        async with maybe_mqtt(mqtt_host, mqtt_port, skip_mqtt) as mqtt:

            async def listen_after_wake(evt: WakeEvent) -> None:
                # Listen for a command after the wake word. If the user
                # spoke, ship the utterance for STT. If it was a bare wake
                # (no speech in the lead-in), publish the wake event so the
                # orchestrator greets — Buggsy prompts "what can I help with?"
                # Prepend preroll so words spoken into the wake-word lag survive.
                wav = await capturer.capture(preroll.snapshot())
                if wav:
                    utt = UtteranceEvent(
                        ts=time.time(),
                        audio_b64=base64.b64encode(wav).decode("ascii"),
                        sample_rate=bus.sample_rate,
                    )
                    await _publish_safe(mqtt, TOPIC_UTTERANCE, utt.model_dump_json())
                    log.info("utterance published: %d bytes wav", len(wav))
                else:
                    await _publish_safe(mqtt, TOPIC_WAKE, evt.model_dump_json())
                    log.info("bare wake -> greeting prompt")

            async def go_attentive(evt: WakeEvent) -> None:
                nonlocal state, last_wake_ts, capture_task
                last_wake_ts = evt.ts
                if state == State.IDLE:
                    state = State.WOKEN
                    log.info("WAKE confidence=%.3f -> attentive", evt.confidence)
                    motion.attentive_pose()
                    # Listen for the command. Skip if a listen is still
                    # running (rapid re-wake).
                    if capture_task is None or capture_task.done():
                        capture_task = asyncio.create_task(listen_after_wake(evt), name="utterance")
                    else:
                        log.info("capture already in progress — not restarting")
                else:
                    log.info("WAKE (already attentive) confidence=%.3f", evt.confidence)

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

            async def handle_speak(payload: bytes) -> None:
                try:
                    cmd = SpeakCommand.model_validate_json(payload)
                except Exception as e:
                    log.warning("bad speak command: %s", e)
                    return
                log.info("SPEAK received: text=%r voice_id=%r audio=%s",
                         cmd.text, cmd.voice_id,
                         "inline" if cmd.audio_b64 else (cmd.audio_url or "none"))
                if not cmd.audio_b64:
                    log.warning("speak with no inline audio — skipping playback")
                    return
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None, play_wav_b64, cmd.audio_b64, output_device, output_volume
                    )
                except Exception as e:
                    log.warning("playback failed: %s", e)
                asyncio.create_task(_publish_safe(
                    mqtt, TOPIC_SPOKE_DONE,
                    SpokeDoneEvent(ts=time.time()).model_dump_json(),
                ))

            async def handle_move(payload: bytes) -> None:
                try:
                    cmd = MoveCommand.model_validate_json(payload)
                except Exception as e:
                    log.warning("bad move command: %s", e)
                    return
                uuid_resp = await asyncio.to_thread(
                    daemon_play_recorded_move, daemon_url, cmd.dataset, cmd.name,
                )
                log.info("MOVE dispatched: %s/%s uuid=%s turn=%s",
                         cmd.dataset, cmd.name, uuid_resp, cmd.turn_id)

            async def cmd_listener() -> None:
                # Single consumer of mqtt.messages — multiple iterators would
                # race for messages and steal them from each other.
                if mqtt is None:
                    return
                await mqtt.subscribe(TOPIC_SPEAK)
                await mqtt.subscribe(TOPIC_MOVE)
                async for msg in mqtt.messages:
                    topic = msg.topic.value
                    if topic == TOPIC_SPEAK:
                        await handle_speak(msg.payload)
                    elif topic == TOPIC_MOVE:
                        await handle_move(msg.payload)

            loop = asyncio.get_running_loop()

            def fire_fake_wake() -> None:
                log.info("SIGUSR1 -> fake wake")
                loop.create_task(go_attentive(WakeEvent(ts=time.time(), confidence=1.0)))

            loop.add_signal_handler(signal.SIGUSR1, fire_fake_wake)

            tasks = [
                asyncio.create_task(cooldown_watcher(), name="cooldown"),
                asyncio.create_task(heartbeat(), name="heartbeat"),
                asyncio.create_task(cmd_listener(), name="cmd_listener"),
            ]

            # Wake the robot only once mic + MQTT are live, so the visual cue
            # (antennae raise, head lift) is a true "I'm listening" signal.
            # to_thread keeps the ~3s settle from blocking the event loop —
            # the heartbeat / speak_listener tasks above stay responsive.
            if not use_mock and not skip_daemon_wake:
                await asyncio.to_thread(daemon_wake_up, daemon_url)

            log.info("agent ready (mock_motion=%s, mqtt=%s, cooldown=%.1fs, vol=%.2f, vad=%.2f)",
                     use_mock, mqtt is not None, cooldown_s, output_volume, cfg.wake.vad_threshold)
            try:
                await run_wake_detection(bus, detector, go_attentive, debounce_s=cfg.wake.debounce_seconds)
            finally:
                if capture_task is not None:
                    tasks.append(capture_task)
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                preroll.stop()
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
