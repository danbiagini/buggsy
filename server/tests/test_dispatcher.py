from pydantic import BaseModel

from server.orchestrator.skills import (
    SkillContext,
    SkillRegistry,
    SkillResult,
    ToolCall,
    dispatch,
)


class _SayParams(BaseModel):
    text: str


class _RecordingSay:
    name = "say"
    description = "say"
    Params = _SayParams

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, params, ctx):
        self.calls.append(params.text)
        return SkillResult(ok=True, skill=self.name)


class _BoomParams(BaseModel):
    pass


class _Boom:
    name = "boom"
    description = "always crashes"
    Params = _BoomParams

    async def run(self, params, ctx):
        raise RuntimeError("kaboom")


def _ctx() -> SkillContext:
    # mqtt/http aren't used by the test skills above
    return SkillContext(mqtt=None, http=None, turn_id="t-test")  # type: ignore[arg-type]


async def test_happy_path_runs_in_order():
    say = _RecordingSay()
    reg = SkillRegistry([say])
    results = await dispatch(
        [ToolCall("say", {"text": "hi"}), ToolCall("say", {"text": "again"})],
        reg, _ctx(),
    )
    assert say.calls == ["hi", "again"]
    assert [r.ok for r in results] == [True, True]


async def test_unknown_skill_falls_back_to_say():
    say = _RecordingSay()
    reg = SkillRegistry([say])
    results = await dispatch([ToolCall("nope", {})], reg, _ctx())
    assert [r.ok for r in results] == [False, True]
    assert say.calls == ["Sorry, I didn't catch that."]


async def test_failed_say_does_not_recurse():
    say = _RecordingSay()
    reg = SkillRegistry([say])
    # missing required `text` -> ValidationError; must NOT trigger another say.
    results = await dispatch([ToolCall("say", {})], reg, _ctx())
    assert [r.ok for r in results] == [False]
    assert say.calls == []


async def test_runtime_error_falls_back():
    say = _RecordingSay()
    reg = SkillRegistry([say, _Boom()])
    results = await dispatch([ToolCall("boom", {})], reg, _ctx())
    assert results[0].ok is False
    assert "kaboom" in results[0].detail
    assert results[1].ok is True
    assert say.calls == ["Sorry, I didn't catch that."]


async def test_first_failure_halts_remaining_calls():
    say = _RecordingSay()
    reg = SkillRegistry([say, _Boom()])
    await dispatch(
        [ToolCall("boom", {}), ToolCall("say", {"text": "should-not-run"})],
        reg, _ctx(),
    )
    assert say.calls == ["Sorry, I didn't catch that."]
