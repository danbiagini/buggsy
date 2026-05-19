"""Move catalog loader.

Fetches recorded-move names from the Reachy daemon for each configured
dataset, joins them with curated descriptions from `buggsy.yaml`, caches
to disk for offline boot, and exposes the result to the planner and to
`PlayMoveSkill` for validation.

Three boot states (design doc §5):

| Daemon       | Cache       | Result                                            |
|--------------|-------------|---------------------------------------------------|
| reachable    | any         | fetch, replace cache, full capability             |
| unreachable  | present     | load cache, full capability (background retry)    |
| unreachable  | absent      | `say`-only mode, background retry                 |

When in `say`-only mode `list_entries()` returns `[]`, so the planner
can simply omit `play_move` from the LLM tool spec — cleaner than
offering a skill that will only reject.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

CACHE_VERSION = 1
FETCH_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class CatalogEntry:
    dataset: str
    name: str
    description: str


class MoveCatalog:
    def __init__(
        self,
        datasets: list[str],
        descriptions: dict[str, str],
        cache_path: Path,
        refresh_seconds: float,
        http: httpx.AsyncClient,
    ) -> None:
        self._datasets = list(datasets)
        self._descriptions = dict(descriptions)
        self._cache_path = Path(cache_path)
        self._refresh_seconds = refresh_seconds
        self._http = http
        self._daemon_url: str | None = None
        self._state: dict[str, list[str]] = {}
        self._retry_task: asyncio.Task | None = None

    # ── public API ──────────────────────────────────────────────────

    async def start(self, daemon_url: str) -> None:
        self._daemon_url = daemon_url
        fetched, fallback = await self._fetch_all()
        if fetched > 0:
            log.info(
                "move catalog ready: %d datasets fresh from daemon, %d from cache, %d selectable entries",
                fetched, fallback, len(self.list_entries()),
            )
        elif fallback > 0:
            log.warning(
                "move catalog: daemon unreachable — using cached entries for %d datasets; "
                "retrying in background every %.0fs",
                fallback, self._refresh_seconds,
            )
            self._start_retry()
        else:
            log.warning(
                "move catalog: daemon unreachable and no cache — say-only mode; "
                "retrying daemon every %.0fs",
                self._refresh_seconds,
            )
            self._start_retry()

    async def stop(self) -> None:
        if self._retry_task is not None:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except (asyncio.CancelledError, Exception):
                pass
            self._retry_task = None

    def is_known(self, dataset: str, name: str) -> bool:
        return name in self._state.get(dataset, [])

    def total_known(self) -> int:
        """Total move-name count across all datasets (including ones
        without descriptions)."""
        return sum(len(v) for v in self._state.values())

    def list_entries(self) -> list[CatalogEntry]:
        entries: list[CatalogEntry] = []
        for dataset, names in self._state.items():
            for name in names:
                desc = self._descriptions.get(f"{dataset}/{name}")
                if desc:
                    entries.append(CatalogEntry(dataset=dataset, name=name, description=desc))
        return entries

    # ── internals ───────────────────────────────────────────────────

    def _start_retry(self) -> None:
        if self._retry_task is None or self._retry_task.done():
            self._retry_task = asyncio.create_task(self._retry_loop(), name="catalog_retry")

    async def _retry_loop(self) -> None:
        while True:
            await asyncio.sleep(self._refresh_seconds)
            fetched, _ = await self._fetch_all()
            if fetched > 0:
                log.info(
                    "background catalog refresh succeeded: %d selectable entries",
                    len(self.list_entries()),
                )
                return

    async def _fetch_all(self) -> tuple[int, int]:
        """Fetch every configured dataset; for any failures fall back to
        the on-disk cache entry. Returns (fresh_count, cache_fallback_count).
        """
        if self._daemon_url is None:
            return 0, 0
        cached_data = self._load_cache() or {}
        fetched = 0
        fallback = 0
        for dataset in self._datasets:
            names = await self._fetch_one(dataset)
            if names is not None:
                self._state[dataset] = names
                self._write_cache_entry(dataset, names)
                fetched += 1
            elif dataset in cached_data:
                self._state[dataset] = cached_data[dataset]
                fallback += 1
                log.info("dataset %s: using cached entry (daemon fetch failed)", dataset)
            else:
                log.warning("dataset %s: fetch failed and no cache — skipping", dataset)
        if fetched > 0 or fallback > 0:
            self._log_mismatches()
        return fetched, fallback

    async def _fetch_one(self, dataset: str) -> list[str] | None:
        assert self._daemon_url is not None
        url = f"{self._daemon_url}/api/move/recorded-move-datasets/list/{dataset}"
        try:
            r = await self._http.get(url, timeout=FETCH_TIMEOUT_S)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("daemon fetch %s -> %s", dataset, e)
            return None
        if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
            log.warning("daemon returned unexpected shape for %s: %r", dataset, data)
            return None
        return data

    def _log_mismatches(self) -> None:
        known: set[str] = set()
        for ds, names in self._state.items():
            for n in names:
                known.add(f"{ds}/{n}")
        described = set(self._descriptions)
        no_desc = sorted(known - described)
        stale = sorted(described - known)
        if no_desc:
            log.info(
                "moves on robot without descriptions (not selectable until described): %s",
                no_desc,
            )
        if stale:
            log.warning("descriptions in config with no matching move on robot: %s", stale)

    def _load_cache(self) -> dict[str, list[str]] | None:
        if not self._cache_path.is_file():
            return None
        try:
            with self._cache_path.open() as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("failed to read cache %s: %s", self._cache_path, e)
            return None
        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
            log.warning("cache version mismatch or invalid shape at %s — ignoring", self._cache_path)
            return None
        result: dict[str, list[str]] = {}
        for ds, entry in (data.get("datasets") or {}).items():
            moves = entry.get("moves") if isinstance(entry, dict) else None
            if isinstance(moves, list) and all(isinstance(m, str) for m in moves):
                result[ds] = moves
        return result or None

    def _write_cache_entry(self, dataset: str, names: list[str]) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {}
            if self._cache_path.is_file():
                try:
                    with self._cache_path.open() as f:
                        data = json.load(f)
                except (OSError, json.JSONDecodeError):
                    data = {}
            if not isinstance(data, dict):
                data = {}
            datasets = data.get("datasets") if isinstance(data.get("datasets"), dict) else {}
            datasets[dataset] = {"moves": list(names), "fetched_at": time.time()}
            new_data = {"version": CACHE_VERSION, "datasets": datasets}
            tmp = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
            with tmp.open("w") as f:
                json.dump(new_data, f, indent=2)
            tmp.replace(self._cache_path)
        except OSError as e:
            log.warning("failed to write cache %s: %s", self._cache_path, e)
