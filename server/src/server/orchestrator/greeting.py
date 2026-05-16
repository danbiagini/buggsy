"""Greeting source implementations.

`StaticGreetingSource` returns a configured phrase. Future: `LlmGreetingSource`
will generate per-interaction greetings via Ollama/Claude.
"""

from __future__ import annotations


class StaticGreetingSource:
    def __init__(self, phrase: str) -> None:
        self._phrase = phrase

    async def get_greeting(self, context: dict | None = None) -> str:
        return self._phrase
