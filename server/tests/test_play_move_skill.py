import json

from server.orchestrator.skills import (
    PlayMoveParams,
    PlayMoveSkill,
    SkillContext,
    SkillRegistry,
    ToolCall,
    dispatch,
)


class _FakeMqtt:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, topic, payload, **kwargs):
        self.published.append((topic, payload))


def _ctx(mqtt) -> SkillContext:
    return SkillContext(mqtt=mqtt, http=None, turn_id="t-play")  # type: ignore[arg-type]


async def test_play_move_publishes_command():
    mqtt = _FakeMqtt()
    skill = PlayMoveSkill()
    result = await skill.run(
        PlayMoveParams(
            dataset="pollen-robotics/reachy-mini-dances-library",
            name="dance_happy",
        ),
        _ctx(mqtt),
    )
    assert result.ok
    assert len(mqtt.published) == 1
    topic, payload = mqtt.published[0]
    assert topic == "buggsy/cmd/move"
    cmd = json.loads(payload)
    assert cmd["dataset"] == "pollen-robotics/reachy-mini-dances-library"
    assert cmd["name"] == "dance_happy"
    assert cmd["turn_id"] == "t-play"


async def test_play_move_dispatched_via_registry():
    # Verify the skill is wired correctly through the dispatcher path the
    # planner will use (validates Params + drives skill.run end-to-end).
    mqtt = _FakeMqtt()
    reg = SkillRegistry([PlayMoveSkill()])
    results = await dispatch(
        [ToolCall("play_move", {
            "dataset": "pollen-robotics/reachy-mini-emotions-library",
            "name": "curious",
        })],
        reg,
        _ctx(mqtt),
    )
    assert [r.ok for r in results] == [True]
    cmd = json.loads(mqtt.published[0][1])
    assert cmd["name"] == "curious"


async def test_play_move_missing_field_rejected():
    mqtt = _FakeMqtt()
    reg = SkillRegistry([PlayMoveSkill()])
    results = await dispatch(
        [ToolCall("play_move", {"dataset": "x"})],  # missing 'name'
        reg,
        _ctx(mqtt),
    )
    assert results[0].ok is False
    assert "invalid params" in results[0].detail
    # No publish on the move topic.
    assert all(t != "buggsy/cmd/move" for t, _ in mqtt.published)


class _StubCatalog:
    def __init__(self, known: set[tuple[str, str]]) -> None:
        self._known = known

    def is_known(self, dataset: str, name: str) -> bool:
        return (dataset, name) in self._known


async def test_play_move_rejects_unknown_when_catalog_present():
    mqtt = _FakeMqtt()
    catalog = _StubCatalog(known={("ds", "good")})
    skill = PlayMoveSkill(catalog=catalog)
    result = await skill.run(
        PlayMoveParams(dataset="ds", name="hallucinated"),
        _ctx(mqtt),
    )
    assert result.ok is False
    assert "unknown move" in result.detail
    # Did NOT publish — dispatcher will turn this into a fallback `say`.
    assert mqtt.published == []


async def test_play_move_accepts_known_when_catalog_present():
    mqtt = _FakeMqtt()
    catalog = _StubCatalog(known={("ds", "good")})
    skill = PlayMoveSkill(catalog=catalog)
    result = await skill.run(
        PlayMoveParams(dataset="ds", name="good"),
        _ctx(mqtt),
    )
    assert result.ok
    assert mqtt.published[0][0] == "buggsy/cmd/move"
