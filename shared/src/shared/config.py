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
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/buggsy.yaml")


class RobotConfig(BaseModel):
    name: str = "Buggsy"


class WakeConfig(BaseModel):
    model_path: str = "robot/wake_models/hey_jarvis_v0.1.onnx"
    threshold: float = 0.5
    debounce_seconds: float = 2.0
    vad_threshold: float = 0.0
    enable_speex_noise_suppression: bool = False


class GreetingConfig(BaseModel):
    source: Literal["static", "llm"] = "static"
    static_phrase: str = "Hi Dan, what can I help with?"


class TtsConfig(BaseModel):
    voice_id: str | None = None


class MotionPose(BaseModel):
    antenna_deg: float
    head_pitch_deg: float = 0.0
    duration_s: float = 0.3


class MotionConfig(BaseModel):
    cooldown_seconds: float = 5.0
    attentive: MotionPose = Field(default_factory=lambda: MotionPose(antenna_deg=60, head_pitch_deg=10, duration_s=0.3))
    resting: MotionPose = Field(default_factory=lambda: MotionPose(antenna_deg=0, head_pitch_deg=0.0, duration_s=0.5))


class AudioConfig(BaseModel):
    output_volume: float = 1.0
    input_device: int | str | None = None
    output_device: int | str | None = None


class MqttConfig(BaseModel):
    host: str = "localhost"
    port: int = 1883


class DaemonConfig(BaseModel):
    url: str = "http://localhost:8000"


class TtsServiceConfig(BaseModel):
    url: str = "http://localhost:8001"


def _default_cache_path() -> Path:
    return Path("~/.cache/buggsy/move_catalog.json").expanduser()


class MovesConfig(BaseModel):
    datasets: list[str] = Field(
        default_factory=lambda: [
            "pollen-robotics/reachy-mini-dances-library",
            "pollen-robotics/reachy-mini-emotions-library",
        ]
    )
    # Keys are "{dataset}/{move}", values are one-line descriptions used in
    # the LLM tool spec. Run `python -m server.tools.refresh_move_catalog`
    # against a live daemon to discover real move names, then fill in.
    descriptions: dict[str, str] = Field(default_factory=dict)
    cache_path: Path = Field(default_factory=_default_cache_path)
    # Background retry interval when the daemon was unreachable at startup.
    refresh_seconds: float = 30.0

    @field_validator("cache_path", mode="before")
    @classmethod
    def _expand_cache_path(cls, v):
        return Path(v).expanduser() if v is not None else v


class BuggsyConfig(BaseModel):
    robot: RobotConfig = Field(default_factory=RobotConfig)
    wake: WakeConfig = Field(default_factory=WakeConfig)
    greeting: GreetingConfig = Field(default_factory=GreetingConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    motion: MotionConfig = Field(default_factory=MotionConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    tts_service: TtsServiceConfig = Field(default_factory=TtsServiceConfig)
    moves: MovesConfig = Field(default_factory=MovesConfig)


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
