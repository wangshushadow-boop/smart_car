"""Common tool request and result types."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict = Field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    success: bool
    data: dict = Field(default_factory=dict)
    error: str | None = None
