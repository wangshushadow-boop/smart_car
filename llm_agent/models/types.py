"""Provider-independent model request and response types."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: str
    user_prompt: str
    # 多模态媒体统一使用 data URL 或 Provider 可访问的 URI。
    audio_data_urls: list[str] = Field(default_factory=list)
    image_data_urls: list[str] = Field(default_factory=list)
    video_data_urls: list[str] = Field(default_factory=list)
    max_tokens: int = Field(default=256, ge=1, le=4096)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    provider: str = "unknown"


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=10_000)


class SpeechResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_wav: bytes = Field(min_length=1)
    provider: str
    sample_rate: int = Field(gt=0)
    channels: int = Field(ge=1, le=8)
