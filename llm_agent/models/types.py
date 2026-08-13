"""与 Provider 解耦的模型请求/响应类型。

`ModelRequest` 把多模态输入统一为 data URL 列表，避免各 Provider 自行
处理二进制传输细节。`SpeechRequest/Response` 用于文本到 WAV 的合成。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelRequest(BaseModel):
    """单次文本推理请求。

    多模态媒体（音频/图片/视频）统一以 data URL 或 Provider 可访问的 URI
    表示，节点的 `runtime.media.model_inputs()` 完成转换。
    """

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
    """推理结果：纯文本回复 + Provider 名称（用于日志与诊断）。"""

    model_config = ConfigDict(extra="forbid")

    text: str
    provider: str = "unknown"


class SpeechRequest(BaseModel):
    """TTS 请求：限定文本长度，避免误用为长篇朗读。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=10_000)


class SpeechResponse(BaseModel):
    """TTS 响应：必须是非空 WAV 字节流，并携带采样率/声道数。"""

    model_config = ConfigDict(extra="forbid")

    audio_wav: bytes = Field(min_length=1)
    provider: str
    sample_rate: int = Field(gt=0)
    channels: int = Field(ge=1, le=8)


class TranscriptionRequest(BaseModel):
    """一次离线语音识别请求。"""

    model_config = ConfigDict(extra="forbid")
    audio_data_urls: list[str] = Field(min_length=1)
    language: str | None = None


class TranscriptionResponse(BaseModel):
    """归一化的语音识别结果。"""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    provider: str
    language: str = ""
