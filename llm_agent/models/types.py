"""Provider-independent model request and response types."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: str
    user_prompt: str
    speech_wav: bytes | None = None
    image_data_url: str | None = None
    max_tokens: int = Field(default=256, ge=1, le=4096)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
