"""与具体 Provider 解耦的模型接口。

所有 Provider（MiniCPM、MiniMax 等）必须实现这两个协议：
- `GenerationBackend`：多模态文本推理。
- `SpeechBackend`：文本 → WAV 合成。

`ModelBackend` 仅为兼容早期架构命名的别名，新代码请使用 `GenerationBackend`。
"""

from __future__ import annotations

from typing import Protocol

from .capabilities import GenerationCapabilities, SpeechCapabilities
from .types import (
    ModelRequest,
    ModelResponse,
    SpeechRequest,
    SpeechResponse,
    TranscriptionRequest,
    TranscriptionResponse,
)


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


# Compatibility name for the first architecture revision.
ModelBackend = GenerationBackend
