"""Capabilities advertised by generation and speech providers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GenerationCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text_input: bool = True
    image_input: bool = False
    audio_input: bool = False
    video_input: bool = False
    tool_calling: bool = False


class SpeechCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    wav_output: bool = True
    streaming: bool = False
    configurable_voice: bool = False
