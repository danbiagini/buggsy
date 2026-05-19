"""Packaged move descriptions for the LLM planner.

Each `<dataset>.yaml` file holds curated, one-line descriptions for the
moves in a HuggingFace recorded-move dataset. Filenames substitute "/"
in the dataset id with "__" since "/" is not legal in a filename:

    pollen-robotics/reachy-mini-dances-library
        -> pollen-robotics__reachy-mini-dances-library.yaml

YAML keys are move names; values are the description strings. The
orchestrator merges these defaults with any overrides under
`moves.descriptions:` in buggsy.yaml (config wins) before constructing
the catalog.
"""

from __future__ import annotations

import logging
from importlib.resources import files

import yaml

log = logging.getLogger(__name__)

_PKG = "server.orchestrator.move_descriptions"


def _filename_for(dataset: str) -> str:
    return dataset.replace("/", "__") + ".yaml"


def load_packaged_descriptions(datasets: list[str]) -> dict[str, str]:
    """Load `{dataset}/{move}: description` entries from packaged YAML
    files for each requested dataset. Missing files are silently skipped
    — they just mean nothing is curated yet for that dataset."""
    out: dict[str, str] = {}
    pkg = files(_PKG)
    for dataset in datasets:
        resource = pkg / _filename_for(dataset)
        if not resource.is_file():
            log.info("no packaged descriptions for dataset %s", dataset)
            continue
        try:
            data = yaml.safe_load(resource.read_text()) or {}
        except yaml.YAMLError as e:
            log.warning("failed to parse descriptions for %s: %s", dataset, e)
            continue
        if not isinstance(data, dict):
            log.warning("descriptions file for %s is not a mapping", dataset)
            continue
        for name, desc in data.items():
            if isinstance(name, str) and isinstance(desc, str):
                out[f"{dataset}/{name}"] = desc
    return out
