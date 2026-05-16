"""Thin wrapper around the Reachy Mini SDK for the Buggsy poses we need.

Wraps `ReachyMini.goto_target()` with named poses parameterized by
`shared.config.MotionPose`. The caller owns the `ReachyMini` connection
and passes it in.

MockMotion is a no-op stand-in for running the agent on a dev machine
without a robot.
"""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

from shared.config import MotionPose

log = logging.getLogger(__name__)


class MotionLike(Protocol):
    def attentive_pose(self) -> None: ...
    def resting_pose(self) -> None: ...
    def speaking_gesture(self) -> None: ...


class Motion:
    def __init__(self, mini, attentive: MotionPose, resting: MotionPose) -> None:
        self._mini = mini
        self._attentive = attentive
        self._resting = resting
        from reachy_mini.utils import create_head_pose
        self._create_head_pose = create_head_pose

    def _goto(self, pose: MotionPose) -> None:
        self._mini.goto_target(
            head=self._create_head_pose(pitch=pose.head_pitch_deg),
            antennas=np.deg2rad([pose.antenna_deg, pose.antenna_deg]),
            duration=pose.duration_s,
            method="minjerk",
        )

    def attentive_pose(self) -> None:
        log.info("motion: attentive_pose")
        self._goto(self._attentive)

    def resting_pose(self) -> None:
        log.info("motion: resting_pose")
        self._goto(self._resting)

    def speaking_gesture(self) -> None:
        # Stub: a small antenna wiggle while talking.
        pass


class MockMotion:
    def attentive_pose(self) -> None:
        log.info("mock motion: attentive_pose")

    def resting_pose(self) -> None:
        log.info("mock motion: resting_pose")

    def speaking_gesture(self) -> None:
        log.info("mock motion: speaking_gesture")
