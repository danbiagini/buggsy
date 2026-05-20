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


class UtteranceConfig(BaseModel):
    lead_in_seconds: float = 2.5   # wait this long for speech to START after wake;
                                   # if none, it's a bare wake -> greeting prompt
    max_seconds: float = 8.0       # hard cap on a single captured utterance
    silence_seconds: float = 0.8   # trailing silence that ends capture
    silence_rms: float = 400.0     # int16 RMS below this counts as silence


class MqttConfig(BaseModel):
    host: str = "localhost"
    port: int = 1883


class DaemonConfig(BaseModel):
    url: str = "http://localhost:8000"


class TtsServiceConfig(BaseModel):
    url: str = "http://localhost:8001"


class SttServiceConfig(BaseModel):
    url: str = "http://localhost:8002"
    # Optional ISO 639-1 language code (e.g. "en"). None lets Whisper
    # auto-detect per utterance.
    language: str | None = None


class MovesConfig(BaseModel):
    datasets: list[str] = Field(
        default_factory=lambda: [
            "pollen-robotics/reachy-mini-dances-library",
            "pollen-robotics/reachy-mini-emotions-library",
        ]
    )
    # Per-move description overrides, keyed by "{dataset}/{move}". Merged
    # on top of the packaged defaults under
    # server/orchestrator/move_descriptions/. Run
    #   python -m server.tools.list_moves
    # against a live daemon to discover real names.
    descriptions: dict[str, str] = Field(default_factory=dict)


class BuggsyConfig(BaseModel):
    robot: RobotConfig = Field(default_factory=RobotConfig)
    wake: WakeConfig = Field(default_factory=WakeConfig)
    greeting: GreetingConfig = Field(default_factory=GreetingConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    motion: MotionConfig = Field(default_factory=MotionConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    utterance: UtteranceConfig = Field(default_factory=UtteranceConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    tts_service: TtsServiceConfig = Field(default_factory=TtsServiceConfig)
    stt_service: SttServiceConfig = Field(default_factory=SttServiceConfig)
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
