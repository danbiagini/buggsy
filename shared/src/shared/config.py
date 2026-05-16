"""Buggsy config loader.

Loads `config/buggsy.yaml` (or `$BUGGSY_CONFIG`) into a typed pydantic
model. Missing file -> defaults; missing fields -> defaults. Callers
should layer env-var overrides on top after loading.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/buggsy.yaml")


class RobotConfig(BaseModel):
    name: str = "Buggsy"


class WakeConfig(BaseModel):
    model_path: str = "robot/wake_models/hey_jarvis_v0.1.onnx"
    threshold: float = 0.5


class GreetingConfig(BaseModel):
    source: Literal["static", "llm"] = "static"
    static_phrase: str = "Hi Dan, what can I help with?"


class TtsConfig(BaseModel):
    voice_id: str | None = None


class MotionConfig(BaseModel):
    cooldown_seconds: float = 5.0


class BuggsyConfig(BaseModel):
    robot: RobotConfig = Field(default_factory=RobotConfig)
    wake: WakeConfig = Field(default_factory=WakeConfig)
    greeting: GreetingConfig = Field(default_factory=GreetingConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    motion: MotionConfig = Field(default_factory=MotionConfig)


def load_config(path: Path | str | None = None) -> BuggsyConfig:
    if path is None:
        env_path = os.environ.get("BUGGSY_CONFIG")
        path = Path(env_path) if env_path else DEFAULT_CONFIG_PATH
    path = Path(path)
    if not path.is_file():
        log.warning("config file not found at %s — using defaults", path)
        return BuggsyConfig()
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    cfg = BuggsyConfig.model_validate(data)
    log.info("loaded config from %s", path)
    return cfg
