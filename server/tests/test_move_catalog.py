import asyncio
import json
from pathlib import Path

import httpx
import pytest

from server.orchestrator.move_catalog import CACHE_VERSION, MoveCatalog

DAEMON_URL = "http://daemon.test:8000"
DS1 = "pollen-robotics/reachy-mini-dances-library"
DS2 = "pollen-robotics/reachy-mini-emotions-library"


def _path(dataset: str) -> str:
    return f"/api/move/recorded-move-datasets/list/{dataset}"


def _make_transport(responses: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        for ds, resp in responses.items():
            if req.url.path == _path(ds):
                return resp
        return httpx.Response(404)
    return httpx.MockTransport(handler)


async def test_happy_path_fetches_and_caches(tmp_path: Path):
    cache = tmp_path / "catalog.json"
    transport = _make_transport({
        DS1: httpx.Response(200, json=["dance_a", "dance_b"]),
        DS2: httpx.Response(200, json=["happy", "curious"]),
    })
    async with httpx.AsyncClient(transport=transport) as http:
        cat = MoveCatalog(
            datasets=[DS1, DS2],
            descriptions={f"{DS1}/dance_a": "a happy dance"},
            cache_path=cache,
            refresh_seconds=999,
            http=http,
        )
        await cat.start(DAEMON_URL)
        try:
            assert cat.is_known(DS1, "dance_a")
            assert cat.is_known(DS2, "curious")
            assert not cat.is_known(DS1, "missing")
            # Only described moves appear in list_entries
            entries = cat.list_entries()
            assert len(entries) == 1
            assert entries[0].name == "dance_a"
            assert entries[0].description == "a happy dance"
            assert cat.total_known() == 4
        finally:
            await cat.stop()

    # Cache file written with both datasets
    on_disk = json.loads(cache.read_text())
    assert on_disk["version"] == CACHE_VERSION
    assert set(on_disk["datasets"]) == {DS1, DS2}
    assert on_disk["datasets"][DS1]["moves"] == ["dance_a", "dance_b"]


async def test_partial_failure_uses_cache_for_failed_dataset(tmp_path: Path):
    cache = tmp_path / "catalog.json"
    # Seed cache with both datasets so the second can fall back.
    cache.write_text(json.dumps({
        "version": CACHE_VERSION,
        "datasets": {
            DS1: {"moves": ["old_a"], "fetched_at": 0},
            DS2: {"moves": ["cached_emotion"], "fetched_at": 0},
        },
    }))
    transport = _make_transport({
        DS1: httpx.Response(200, json=["fresh_a", "fresh_b"]),
        DS2: httpx.Response(500),  # daemon hiccup on this one
    })
    async with httpx.AsyncClient(transport=transport) as http:
        cat = MoveCatalog([DS1, DS2], {}, cache, 999, http)
        await cat.start(DAEMON_URL)
        try:
            # DS1 fresh from daemon
            assert cat.is_known(DS1, "fresh_a")
            assert not cat.is_known(DS1, "old_a")
            # DS2 fell back to cache
            assert cat.is_known(DS2, "cached_emotion")
        finally:
            await cat.stop()

    # DS1 cache replaced; DS2 cache NOT clobbered with empty/bad data
    on_disk = json.loads(cache.read_text())
    assert on_disk["datasets"][DS1]["moves"] == ["fresh_a", "fresh_b"]
    assert on_disk["datasets"][DS2]["moves"] == ["cached_emotion"]


async def test_daemon_down_with_cache_loads_cache(tmp_path: Path):
    cache = tmp_path / "catalog.json"
    cache.write_text(json.dumps({
        "version": CACHE_VERSION,
        "datasets": {DS1: {"moves": ["c1", "c2"], "fetched_at": 0}},
    }))
    # All requests fail
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        cat = MoveCatalog([DS1], {}, cache, 999, http)
        await cat.start(DAEMON_URL)
        try:
            assert cat.is_known(DS1, "c1")
            assert cat.total_known() == 2
        finally:
            await cat.stop()


async def test_daemon_down_no_cache_say_only(tmp_path: Path):
    cache = tmp_path / "catalog.json"  # does not exist
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        cat = MoveCatalog([DS1], {DS1 + "/x": "desc"}, cache, 999, http)
        await cat.start(DAEMON_URL)
        try:
            assert cat.total_known() == 0
            assert cat.list_entries() == []
            assert not cat.is_known(DS1, "x")
        finally:
            await cat.stop()


async def test_background_retry_recovers(tmp_path: Path):
    cache = tmp_path / "catalog.json"
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        # First call fails; subsequent calls succeed.
        if call_count["n"] <= 1:
            return httpx.Response(500)
        return httpx.Response(200, json=["recovered"])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        cat = MoveCatalog([DS1], {}, cache, refresh_seconds=0.02, http=http)
        await cat.start(DAEMON_URL)
        try:
            assert cat.total_known() == 0  # initial fetch failed, no cache
            # Wait long enough for the retry task to fire and succeed
            for _ in range(50):
                if cat.total_known() > 0:
                    break
                await asyncio.sleep(0.02)
            assert cat.is_known(DS1, "recovered")
        finally:
            await cat.stop()


async def test_unexpected_response_shape_treated_as_failure(tmp_path: Path):
    cache = tmp_path / "catalog.json"
    transport = _make_transport({
        DS1: httpx.Response(200, json={"not": "a list"}),
    })
    async with httpx.AsyncClient(transport=transport) as http:
        cat = MoveCatalog([DS1], {}, cache, 999, http)
        await cat.start(DAEMON_URL)
        try:
            assert cat.total_known() == 0
        finally:
            await cat.stop()


async def test_cache_version_mismatch_ignored(tmp_path: Path):
    cache = tmp_path / "catalog.json"
    cache.write_text(json.dumps({
        "version": 999,
        "datasets": {DS1: {"moves": ["stale"], "fetched_at": 0}},
    }))
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        cat = MoveCatalog([DS1], {}, cache, 999, http)
        await cat.start(DAEMON_URL)
        try:
            assert cat.total_known() == 0
        finally:
            await cat.stop()
