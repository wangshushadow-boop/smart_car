"""AgentRuntime 使用的统一全模态领域契约。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContentType(str, Enum):
    """请求和响应支持的内容模态。"""

    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    VIDEO = "video"
    JSON = "json"


class ContentPart(BaseModel):
    """单个内容块；二进制内容可内联，也可保留外部引用。"""

    model_config = ConfigDict(extra="forbid")

    type: ContentType
    name: str = ""
    mime_type: str = ""
    text: str = ""
    data: bytes = b""
    uri: str = ""
    topic: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "ContentPart":
        if self.type in {ContentType.TEXT, ContentType.JSON}:
            if not self.text.strip():
                raise ValueError("文本或 JSON 内容不能为空")
        elif not (self.data or self.uri or self.topic):
            raise ValueError("二进制模态必须提供 data、uri 或 topic")
        return self


class RuntimeRequest(BaseModel):
    """所有调用方进入 Runtime 的唯一请求类型。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    session_id: str = ""
    source: str = Field(default="unknown", min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    inputs: list[ContentPart] = Field(min_length=1)
    response_modalities: list[ContentType] = Field(
        default_factory=lambda: [ContentType.TEXT]
    )
    allow_tools: bool = True
    stream_progress: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_modalities(self) -> "RuntimeRequest":
        # 当前回复节点始终生成文字；音频等其他模态在文字基础上派生。
        if ContentType.TEXT not in self.response_modalities:
            self.response_modalities.insert(0, ContentType.TEXT)
        self.response_modalities = list(dict.fromkeys(self.response_modalities))
        return self


class RuntimeProgress(BaseModel):
    """Runtime 向传输层报告的粗粒度执行进度。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    stage: str
    percent: int = Field(ge=0, le=100)
    message: str
    partial_outputs: list[ContentPart] = Field(default_factory=list)


class RuntimeResponse(BaseModel):
    """Runtime 的统一全模态结果。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    session_id: str = ""
    status: str
    outputs: list[ContentPart] = Field(default_factory=list)
    generation_provider: str = ""
    speech_provider: str = ""
    error_code: str = ""
    error_message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
