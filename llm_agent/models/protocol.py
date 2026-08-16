"""与具体 Provider 解耦的模型接口。

所有 Provider（MiniCPM、MiniMax 等）必须实现对应协议：
- `GenerationBackend`：多模态文本推理。
- `SpeechBackend`：文本 → WAV 合成。
"""

from __future__ import annotations

import ast
import io
import json
import re
import wave
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class GenerationCapabilities(BaseModel):
    """生成 Provider 的输入能力与统一循环参数。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    text_input: bool = True
    image_input: bool = False
    audio_input: bool = False
    video_input: bool = False
    tool_calling: bool = False
    # 输出上限属于具体模型能力，由 models.yaml 按 Provider 声明；统一协议只
    # 校验正数，不再用本地常量截断云端模型支持的最大输出。
    max_output_tokens: int = Field(default=256, ge=1)
    response_temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class SpeechCapabilities(BaseModel):
    """语音 Provider 输出能力。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    wav_output: bool = True
    streaming: bool = False
    configurable_voice: bool = False


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_prompt: str
    user_prompt: str
    audio_data_urls: list[str] = Field(default_factory=list)
    image_data_urls: list[str] = Field(default_factory=list)
    video_data_urls: list[str] = Field(default_factory=list)
    # 请求值由对应 Provider 的能力配置产生，不在跨模型协议层设置上限。
    max_tokens: int = Field(default=256, ge=1)
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


class TranscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_data_urls: list[str] = Field(min_length=1)
    language: str | None = None


class TranscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    provider: str
    language: str = ""


class GenerationBackend(Protocol):
    """文本推理 Provider 协议。"""

    @property
    def provider_name(self) -> str:
        """Stable provider identifier used in configuration and diagnostics."""

    @property
    def capabilities(self) -> GenerationCapabilities:
        """Declare supported request modalities before network access."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Return one text completion for a typed multimodal request."""


class SpeechBackend(Protocol):
    """语音合成 Provider 协议。"""

    @property
    def provider_name(self) -> str:
        """Stable provider identifier used in configuration and diagnostics."""

    @property
    def capabilities(self) -> SpeechCapabilities:
        """Declare supported speech output features."""

    def synthesize(self, request: SpeechRequest) -> SpeechResponse:
        """Synthesize a validated WAV response from final answer text."""


class AsrBackend(Protocol):
    """语音识别 Provider 协议。"""

    @property
    def provider_name(self) -> str:
        """Stable provider identifier used in diagnostics."""

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        """把一段或多段音频转成非空文本。"""


def inspect_pcm16_wav(audio: bytes) -> tuple[int, int]:
    """校验 16-bit 非压缩 PCM WAV，并返回采样率和声道数。"""
    if not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE":
        raise ValueError("speech output is not a WAV file")
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            if source.getsampwidth() != 2:
                raise ValueError("speech WAV must use 16-bit PCM")
            if source.getcomptype() != "NONE":
                raise ValueError("speech WAV must be uncompressed PCM")
            if source.getnframes() <= 0:
                raise ValueError("speech WAV has no frames")
            return source.getframerate(), source.getnchannels()
    except (EOFError, wave.Error) as error:
        raise ValueError(f"invalid speech WAV: {error}") from error


def sanitize_spoken_answer(text: str) -> str:
    """去掉思考、工具调用和 Markdown，仅保留可朗读回答。"""
    assistant_segments = re.findall(
        r"\[AI助手\]\s*(?!\[)([^\[\n]+)", text, flags=re.IGNORECASE
    )
    if assistant_segments:
        text = assistant_segments[-1]
    elif re.match(r"\s*<think\b", text, flags=re.IGNORECASE) and not re.search(
        r"</think>", text, flags=re.IGNORECASE
    ):
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"<(?:tool|function|analysis|commentary)[^>]*>.*?</(?:tool|function|analysis|commentary)>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(
        r"^\s*(?:assistant|final(?:_answer)?|回答|答复)\s*[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[*`_#>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_json_object(text: str) -> dict:
    """安全解析模型返回的 JSON 或单引号字面量对象。"""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("模型未返回 JSON 对象")
    raw_object = match.group(0)
    try:
        try:
            payload = json.loads(raw_object)
        except json.JSONDecodeError:
            payload = ast.literal_eval(raw_object)
        if not isinstance(payload, dict):
            raise ValueError("模型输出根节点必须是对象")
        return payload
    except (SyntaxError, ValueError) as error:
        raise ValueError(f"模型输出格式无效：{error}") from error
