"""与具体实现解耦的语音识别请求和响应。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TranscriptionRequest(BaseModel):
    """一次离线转写请求；当前小车每轮通常只包含一段 WAV。"""

    model_config = ConfigDict(extra="forbid")

    audio_data_urls: list[str] = Field(min_length=1)
    language: str | None = None


class TranscriptionResponse(BaseModel):
    """归一化的 ASR 结果。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    provider: str
    language: str = ""
