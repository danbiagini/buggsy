"""PlayMoveSkill: ask the robot to play a recorded move from a
HuggingFace dataset via the Reachy daemon.

Publishes a `MoveCommand` on `buggsy/cmd/move`; the robot's
`move_listener` turns that into a POST to
`/api/move/play/recorded-move-dataset/{dataset}/{name}` on the daemon.

This v1 skeleton accepts any `(dataset, name)`. #22 (move catalog
loader) adds validation against the catalog of moves the daemon
actually exposes.
"""

from __future__ import annotations

import logging
from typing import Protocol

from pydantic import BaseModel, Field

from shared.protocol import TOPIC_MOVE, MoveCommand

from .base import SkillContext, SkillResult

log = logging.getLogger(__name__)


class CatalogLike(Protocol):
    """Subset of MoveCatalog that PlayMoveSkill needs — narrows the
    coupling for tests."""

    def is_known(self, dataset: str, name: str) -> bool: ...


class PlayMoveParams(BaseModel):
    dataset: str = Field(
        ...,
        description=(
            "HuggingFace dataset id holding the recorded move, e.g. "
            "'pollen-robotics/reachy-mini-dances-library'."
        ),
        min_length=1,
    )
    name: str = Field(
        ...,
        description="Name of the recorded move within the dataset.",
        min_length=1,
    )


class PlayMoveSkill:
    name = "play_move"
    description = (
        "Play a recorded move (dance, emotion, or gesture) on the robot. "
        "Use sparingly — only when the user explicitly asks, or to express "
        "emotion that supports a spoken response."
    )
    Params = PlayMoveParams

    def __init__(self, catalog: CatalogLike | None = None) -> None:
        self._catalog = catalog

    async def run(self, params: PlayMoveParams, ctx: SkillContext) -> SkillResult:
        if self._catalog is not None and not self._catalog.is_known(params.dataset, params.name):
            log.warning(
                "[turn=%s] play_move rejected: %s/%s not in catalog",
                ctx.turn_id, params.dataset, params.name,
            )
            return SkillResult(
                ok=False,
                skill=self.name,
                detail=f"unknown move: {params.dataset}/{params.name}",
            )
        cmd = MoveCommand(dataset=params.dataset, name=params.name, turn_id=ctx.turn_id)
        await ctx.mqtt.publish(TOPIC_MOVE, cmd.model_dump_json())
        log.info("[turn=%s] play_move: %s/%s", ctx.turn_id, params.dataset, params.name)
        return SkillResult(
            ok=True,
            skill=self.name,
            detail=f"{params.dataset}/{params.name}",
        )
