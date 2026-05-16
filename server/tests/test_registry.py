import pytest
from pydantic import BaseModel

from server.orchestrator.skills import SkillRegistry, SkillResult


class _DummyParams(BaseModel):
    x: int


class _Dummy:
    name = "dummy"
    description = "A dummy skill."
    Params = _DummyParams

    async def run(self, params, ctx):
        return SkillResult(ok=True, skill=self.name)


def test_registry_lookup_and_listing():
    reg = SkillRegistry([_Dummy()])
    assert reg.names() == ["dummy"]
    assert reg.get("dummy") is not None
    assert reg.get("missing") is None


def test_registry_rejects_duplicate_names():
    with pytest.raises(ValueError, match="duplicate"):
        SkillRegistry([_Dummy(), _Dummy()])


def test_to_ollama_tools_shape():
    reg = SkillRegistry([_Dummy()])
    tools = reg.to_ollama_tools()
    assert len(tools) == 1
    t = tools[0]
    assert t["type"] == "function"
    assert t["function"]["name"] == "dummy"
    assert t["function"]["description"] == "A dummy skill."
    assert t["function"]["parameters"]["properties"]["x"]["type"] == "integer"
