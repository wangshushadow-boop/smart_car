"""Validated Agent provider configuration with environment overrides."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class GenerationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="minicpm", min_length=1)


class SpeechSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="auto", min_length=1)
    preferred: str = Field(default="same_provider", min_length=1)
    fallback: str = Field(default="piper", min_length=1)


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_inline_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    conversation_enabled: bool = True
    conversation_max_turns: int = Field(default=8, ge=1, le=100)
    conversation_max_context_chars: int = Field(default=12_000, ge=256)
    conversation_ttl_seconds: float = Field(default=1800.0, gt=0)
    conversation_max_sessions: int = Field(default=128, ge=1)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation: GenerationSelection = Field(default_factory=GenerationSelection)
    speech: SpeechSelection = Field(default_factory=SpeechSelection)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    providers: dict[str, dict] = Field(default_factory=dict)


def load_agent_config(path: Path | None = None) -> AgentConfig:
    config_path = path or Path(
        os.getenv(
            "CAR_AGENT_CONFIG",
            str(Path(__file__).resolve().parents[1] / "config" / "agent.yaml"),
        )
    )
    try:
        with config_path.open(encoding="utf-8") as config_file:
            payload = yaml.safe_load(config_file) or {}
    except OSError as error:
        raise RuntimeError(f"cannot load Agent config {config_path}: {error}") from error
    config = AgentConfig.model_validate(payload)
    generation_provider = os.getenv("CAR_GENERATION_PROVIDER")
    speech_provider = os.getenv("CAR_SPEECH_PROVIDER")
    if generation_provider:
        config.generation.provider = generation_provider
    if speech_provider:
        config.speech.provider = speech_provider
    return config
