"""Refresh the move-catalog disk cache from a live Reachy daemon.

Useful from any machine that can reach the daemon — dev mac, CI seed,
or a one-off before deploying the orchestrator to a server that can't
yet reach the robot. Mirrors what the orchestrator does at startup,
but prints what it found so you can curate the `moves.descriptions:`
map in buggsy.yaml.

Usage:
    python -m server.tools.refresh_move_catalog
    BUGGSY_DAEMON_URL=http://reachy-mini.local:8000 python -m server.tools.refresh_move_catalog

Exit status:
    0  at least one dataset was fetched
    1  no datasets could be fetched (daemon unreachable, or all listed
       datasets returned errors)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import httpx

from shared.protocol import load_config

from ..orchestrator.move_catalog import MoveCatalog

log = logging.getLogger("buggsy.tools.refresh_move_catalog")


async def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    daemon_url = os.environ.get("BUGGSY_DAEMON_URL", cfg.daemon.url)
    log.info("daemon: %s", daemon_url)
    log.info("datasets: %s", cfg.moves.datasets)
    log.info("cache:    %s", cfg.moves.cache_path)

    async with httpx.AsyncClient() as http:
        catalog = MoveCatalog(
            datasets=cfg.moves.datasets,
            descriptions=cfg.moves.descriptions,
            cache_path=cfg.moves.cache_path,
            refresh_seconds=cfg.moves.refresh_seconds,
            http=http,
        )
        await catalog.start(daemon_url)
        # Stop the background retry that start() may have spawned.
        await catalog.stop()

        entries = catalog.list_entries()
        if entries:
            print()
            print("Selectable entries (have a description in buggsy.yaml):")
            for e in entries:
                print(f"  {e.dataset}/{e.name}  —  {e.description}")
        # The undescribed list is already in the log output from start().
        return 0 if catalog.total_known() > 0 else 1


def run() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    run()
