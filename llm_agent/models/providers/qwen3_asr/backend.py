"""Qwen3-ASR 独立服务的纯 HTTP 客户端。

Agent 只依赖本客户端的 ``transcribe`` 接口。这里不导入 PyTorch/qwen-asr、
不访问模型文件，也不创建子进程，因此模型服务可以独立启动和停止。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any
from urllib.request import Request, urlopen

from ...protocol import TranscriptionRequest, TranscriptionResponse


class Qwen3Asr:
    """只调用外部 ASR 服务，不加载模型或创建子进程。"""

    provider_name = "qwen3_asr"

    def __init__(
        self,
        settings: dict | None = None,
        *,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        """从 models.yaml 构造客户端；环境变量仅用于临时覆盖调试。"""
        settings = settings or {}
        self._endpoint = os.getenv(
            "QWEN3_ASR_ENDPOINT",
            str(settings.get("endpoint", "http://127.0.0.1:8100")),
        ).rstrip("/")
        self._language = os.getenv(
            "QWEN3_ASR_LANGUAGE", str(settings.get("language", "Chinese"))
        )
        self._timeout = float(settings.get("timeout_seconds", 120))
        self._opener = opener

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        """将标准转写请求发送到 ``POST /transcribe`` 并归一化响应。"""
        payload = {
            "audio_data_urls": request.audio_data_urls,
            "language": request.language or self._language,
        }
        http_request = Request(
            f"{self._endpoint}/transcribe",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(http_request, timeout=self._timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise RuntimeError(f"Qwen3 ASR service request failed: {error}") from error
        if result.get("error"):
            # 服务端业务错误与网络错误统一转成 Runtime 可处理的 RuntimeError。
            raise RuntimeError(str(result["error"]))
        return TranscriptionResponse(
            text=str(result.get("text", "")).strip(),
            provider=str(result.get("provider", self.provider_name)),
            language=str(result.get("language", "")),
        )
