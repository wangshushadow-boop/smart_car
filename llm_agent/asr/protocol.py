"""ASR Provider 协议。"""

from __future__ import annotations

from typing import Protocol

from .types import TranscriptionRequest, TranscriptionResponse


class AsrBackend(Protocol):
    @property
    def provider_name(self) -> str:
        """返回稳定的 Provider 名称。"""

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        """把一段或多段音频转成非空文本。"""
