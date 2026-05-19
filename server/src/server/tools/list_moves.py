"""List recorded moves a live Reachy daemon reports, and mark which ones
have descriptions in the orchestrator's curated set.

A discovery tool, not a setup step — the orchestrator no longer fetches
from the daemon at startup. Use this to:

  * see what's actually installed on a given robot,
  * pick names to write descriptions for under
    `server/orchestrator/move_descriptions/<dataset>.yaml`, or
  * override descriptions via `moves.descriptions:` in buggsy.yaml.

Usage:
    python -m server.tools.list_moves
    BUGGSY_DAEMON_URL=http://reachy-mini.local:8000 python -m server.tools.list_moves

Output (per dataset):
    [✓] welcoming1   Welcoming greeting — open, friendly hello.
    [ ] rage1
    ...
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import httpx

from shared.protocol import load_config

from ..orchestrator.move_descriptions import load_packaged_descriptions

log = logging.getLogger("buggsy.tools.list_moves")

FETCH_TIMEOUT_S = 10.0


async def _fetch_dataset(http: httpx.AsyncClient, daemon_url: str, dataset: str) -> list[str] | None:
    url = f"{daemon_url}/api/move/recorded-move-datasets/list/{dataset}"
    try:
        r = await http.get(url, timeout=FETCH_TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("fetch %s -> %s", dataset, e)
        return None
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        log.warning("unexpected response shape for %s: %r", dataset, data)
        return None
    return data


async def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    daemon_url = os.environ.get("BUGGSY_DAEMON_URL", cfg.daemon.url)
    print(f"daemon: {daemon_url}")
    descriptions = {
        **load_packaged_descriptions(cfg.moves.datasets),
        **cfg.moves.descriptions,
    }

    any_fetched = False
    async with httpx.AsyncClient() as http:
        for dataset in cfg.moves.datasets:
            print()
            print(f"# {dataset}")
            names = await _fetch_dataset(http, daemon_url, dataset)
            if names is None:
                print("  (fetch failed)")
                continue
            any_fetched = True
            for name in names:
                key = f"{dataset}/{name}"
                desc = descriptions.get(key)
                mark = "✓" if desc else " "
                tail = f"   {desc}" if desc else ""
                print(f"  [{mark}] {name}{tail}")

    return 0 if any_fetched else 1


def run() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    run()
