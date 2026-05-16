"""Buggsy agent: wake detection drives a motion state machine.

State machine:
    idle    -> wake event -> woken (attentive_pose)
    woken   -> cooldown_s of no further wake -> idle (resting_pose)

Fake wake (dev): send SIGUSR1 to the process.
    kill -USR1 $(pgrep -f robot.agent.agent)

Usage:
    /venvs/apps_venv/bin/python -m robot.agent.agent
    BUGGSY_MOCK_MOTION=1 python -m robot.agent.agent     # dev mac, no robot

Env vars:
    BUGGSY_WAKE_MODEL       Path to openWakeWord .onnx model.
    BUGGSY_WAKE_THRESHOLD   Wake confidence cutoff. Default: 0.5
    BUGGSY_COOLDOWN_S       Seconds to stay attentive after last wake. Default: 5.0
    BUGGSY_MOCK_MOTION      Set to 1 to skip the Reachy SDK (no real robot needed).
    BUGGSY_AUDIO_DEVICE     sounddevice input device index or name.
    BUGGSY_DAEMON_URL       Reachy daemon base URL. Default: http://localhost:8000
    BUGGSY_SKIP_DAEMON_WAKE Set to 1 to skip the wake/sleep daemon calls (e.g. if
                            you've already woken the robot via Reachy Mini Control).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from enum import Enum

from shared.protocol import WakeEvent

from .audio_bus import AudioBus
from .motion import MockMotion, Motion, MotionLike
from .wake_detector import OpenWakeWordDetector, run_wake_detection

log = logging.getLogger("buggsy.agent")

DEFAULT_MODEL = "robot/wake_models/hey_jarvis_v0.1.onnx"
DEFAULT_COOLDOWN_S = 5.0
DEFAULT_DAEMON_URL = "http://localhost:8000"
WAKE_SETTLE_S = 3.0  # wake_up emote takes ~2-3s; give it time before connecting
REACHY_MIC_NAME_HINT = "Reachy Mini Audio"


def _pick_audio_device(env_value: str | None) -> int | str | None:
    """Resolve the input device.

    - If `BUGGSY_AUDIO_DEVICE` is set, honour it verbatim.
    - Else, scan for an input device whose name contains REACHY_MIC_NAME_HINT
      (avoids pipewire's "default" routing, which doesn't survive the SDK's
      release_media call cleanly).
    - Else, return None (sounddevice picks the system default).
    """
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

    # no_media so the SDK doesn't claim the mic — AudioBus uses sounddevice directly.
    with ReachyMini(media_backend="no_media") as mini:
        yield mini


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    model_path = os.environ.get("BUGGSY_WAKE_MODEL", DEFAULT_MODEL)
    threshold = float(os.environ.get("BUGGSY_WAKE_THRESHOLD", "0.5"))
    cooldown_s = float(os.environ.get("BUGGSY_COOLDOWN_S", str(DEFAULT_COOLDOWN_S)))
    use_mock = os.environ.get("BUGGSY_MOCK_MOTION") == "1"
    daemon_url = os.environ.get("BUGGSY_DAEMON_URL", DEFAULT_DAEMON_URL)
    skip_daemon_wake = os.environ.get("BUGGSY_SKIP_DAEMON_WAKE") == "1"
    device = _pick_audio_device(os.environ.get("BUGGSY_AUDIO_DEVICE"))

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

        async def go_attentive(evt: WakeEvent) -> None:
            nonlocal state, last_wake_ts
            last_wake_ts = evt.ts
            if state == State.IDLE:
                state = State.WOKEN
                log.info("WAKE confidence=%.3f -> attentive", evt.confidence)
                motion.attentive_pose()
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

        loop = asyncio.get_running_loop()

        def fire_fake_wake() -> None:
            log.info("SIGUSR1 -> fake wake")
            loop.create_task(go_attentive(WakeEvent(ts=time.time(), confidence=1.0)))

        loop.add_signal_handler(signal.SIGUSR1, fire_fake_wake)

        watcher = asyncio.create_task(cooldown_watcher())
        log.info("agent ready (mock_motion=%s, cooldown=%.1fs)", use_mock, cooldown_s)
        try:
            await run_wake_detection(bus, detector, go_attentive)
        finally:
            watcher.cancel()
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
