"""Skill registry: lookup by name; export the Ollama tool spec."""

from __future__ import annotations

from typing import Any

from .base import Skill


class SkillRegistry:
    def __init__(self, skills: list[Skill]) -> None:
        self._skills: dict[str, Skill] = {}
        for s in skills:
            if s.name in self._skills:
                raise ValueError(f"duplicate skill name: {s.name!r}")
            self._skills[s.name] = s

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return list(self._skills)

    def to_ollama_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": s.name,
                    "description": s.description,
                    "parameters": s.Params.model_json_schema(),
                },
            }
            for s in self._skills.values()
        ]
