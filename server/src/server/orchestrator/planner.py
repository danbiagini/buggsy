"""Planner: decides which skills to invoke for a given event.

`StubPlanner` is the v2 starting point — always returns a single
`say(static_phrase)`, preserving v1 behavior while the skill framework
and dispatcher take over the execution path. The real LLM-backed
planner replaces it in #25 (LlmPlanner).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .skills import ToolCall


@runtime_checkable
class Planner(Protocol):
    async def plan(self, prompt: str | None = None) -> list[ToolCall]: ...


class StubPlanner:
    """Static planner: emits a single `say` with the configured phrase."""

    def __init__(self, phrase: str) -> None:
        self._phrase = phrase

    async def plan(self, prompt: str | None = None) -> list[ToolCall]:
        return [ToolCall(name="say", params={"text": self._phrase})]
