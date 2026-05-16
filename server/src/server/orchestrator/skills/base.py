"""Skill framework: Skill protocol + supporting types.

A Skill is a unit of work the LLM planner can request via a tool call.
Each skill carries a pydantic Params model for typed validation — the
same model produces the JSON schema fed to Ollama as the tool spec — and
an async `run` that performs the work given validated params and the
orchestrator's per-turn context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import aiomqtt
import httpx
from pydantic import BaseModel


@dataclass(frozen=True)
class SkillContext:
    """Per-turn shared resources passed to every skill invocation."""

    mqtt: aiomqtt.Client
    http: httpx.AsyncClient
    turn_id: str


@dataclass(frozen=True)
class ToolCall:
    """A request from the planner to invoke a named skill with raw params."""

    name: str
    params: dict[str, Any]


@dataclass(frozen=True)
class SkillResult:
    """Outcome of a dispatched tool call."""

    ok: bool
    skill: str
    detail: str = ""


@runtime_checkable
class Skill(Protocol):
    name: str
    description: str
    Params: type[BaseModel]

    async def run(self, params: BaseModel, ctx: SkillContext) -> SkillResult: ...
