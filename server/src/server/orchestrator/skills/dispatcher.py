"""Skill dispatcher.

Validates each ToolCall's params against the skill's pydantic model and
runs the skill. On any failure (unknown skill, bad params, runtime
error), processing stops and a single fallback `say(...)` is emitted so
Buggsy always responds with something.

The planner-side "retry once with the validation error in the prompt"
pattern lives in the planner (see docs/llm_planner.md §3); the
dispatcher itself does not re-prompt the LLM.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from .base import SkillContext, SkillResult, ToolCall
from .registry import SkillRegistry

log = logging.getLogger(__name__)

FALLBACK_TEXT = "Sorry, I didn't catch that."


async def dispatch(
    calls: list[ToolCall],
    registry: SkillRegistry,
    ctx: SkillContext,
    fallback_text: str = FALLBACK_TEXT,
) -> list[SkillResult]:
    results: list[SkillResult] = []
    for call in calls:
        result = await _run_one(call, registry, ctx)
        results.append(result)
        if result.ok:
            continue
        log.warning("[turn=%s] skill %r failed: %s", ctx.turn_id, call.name, result.detail)
        if call.name != "say":
            fb = await _run_one(
                ToolCall(name="say", params={"text": fallback_text}), registry, ctx
            )
            results.append(fb)
        break
    return results


async def _run_one(call: ToolCall, registry: SkillRegistry, ctx: SkillContext) -> SkillResult:
    skill = registry.get(call.name)
    if skill is None:
        return SkillResult(ok=False, skill=call.name, detail="unknown skill")
    try:
        params = skill.Params.model_validate(call.params)
    except ValidationError as e:
        return SkillResult(ok=False, skill=call.name, detail=f"invalid params: {e}")
    try:
        return await skill.run(params, ctx)
    except Exception as e:
        return SkillResult(ok=False, skill=call.name, detail=f"runtime error: {e}")
