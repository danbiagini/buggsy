"""Thin wrapper around the Reachy Mini SDK for the Buggsy poses we need.

Wraps `ReachyMini.goto_target()` with named poses. The caller owns the
`ReachyMini` connection and passes it in — keeps Motion testable and lets
the agent control the SDK lifecycle (including `media_backend="no_media"`
so it doesn't grab the mic out from under our AudioBus).

MockMotion is a no-op stand-in for running the agent on a dev machine
without a robot.
"""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

# Antenna angles in degrees.
ANTENNA_RAISED_DEG = 60
ANTENNA_REST_DEG = 0

# Head pitch in degrees. Positive = forward tilt ("leaning in").
HEAD_ATTENTIVE_PITCH_DEG = 10


class MotionLike(Protocol):
    def attentive_pose(self) -> None: ...
    def resting_pose(self) -> None: ...
    def speaking_gesture(self) -> None: ...


class Motion:
    def __init__(self, mini) -> None:
        self._mini = mini
        from reachy_mini.utils import create_head_pose
        self._create_head_pose = create_head_pose

    def attentive_pose(self, duration: float = 0.3) -> None:
        log.info("motion: attentive_pose")
        self._mini.goto_target(
            head=self._create_head_pose(pitch=HEAD_ATTENTIVE_PITCH_DEG),
            antennas=np.deg2rad([ANTENNA_RAISED_DEG, ANTENNA_RAISED_DEG]),
            duration=duration,
            method="minjerk",
        )

    def resting_pose(self, duration: float = 0.5) -> None:
        log.info("motion: resting_pose")
        self._mini.goto_target(
            head=self._create_head_pose(),
            antennas=np.deg2rad([ANTENNA_REST_DEG, ANTENNA_REST_DEG]),
            duration=duration,
            method="minjerk",
        )

    def speaking_gesture(self) -> None:
        # Stub for #6: a small antenna wiggle while talking.
        pass


class MockMotion:
    def attentive_pose(self, duration: float = 0.3) -> None:
        log.info("mock motion: attentive_pose")

    def resting_pose(self, duration: float = 0.5) -> None:
        log.info("mock motion: resting_pose")

    def speaking_gesture(self) -> None:
        log.info("mock motion: speaking_gesture")
