"""Move catalog: the set of recorded moves the LLM planner is allowed
to invoke.

Backed entirely by the curated description map (packaged YAML +
buggsy.yaml overrides). If a `{dataset}/{move}` has a description, it
is in the catalog; otherwise it is not. There is intentionally no
daemon-side validation: the description files are our source of truth
about what we want the LLM to see, and a stale entry results in a
graceful 4xx that the robot's `daemon_play_recorded_move` already
swallows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogEntry:
    dataset: str
    name: str
    description: str


class MoveCatalog:
    def __init__(self, descriptions: dict[str, str]) -> None:
        # Keys are "{dataset}/{move}".
        self._descriptions = dict(descriptions)

    def is_known(self, dataset: str, name: str) -> bool:
        return f"{dataset}/{name}" in self._descriptions

    def total_known(self) -> int:
        return len(self._descriptions)

    def list_entries(self) -> list[CatalogEntry]:
        entries: list[CatalogEntry] = []
        for key, desc in self._descriptions.items():
            dataset, _, name = key.rpartition("/")
            if not dataset or not name:
                log.warning("malformed catalog key %r — skipped", key)
                continue
            entries.append(CatalogEntry(dataset=dataset, name=name, description=desc))
        return entries
