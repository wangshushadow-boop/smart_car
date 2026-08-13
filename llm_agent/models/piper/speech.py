"""Piper 独立语音服务的纯 HTTP 客户端。

本模块只进行 JSON/Base64 协议转换与 WAV 校验，不执行 Piper 命令，也不访问
ONNX 模型文件。Piper 服务的生命周期完全由 ``start_models.sh`` 管理。
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from typing import Any
from urllib.request import Request, urlopen

from llm_agent.models.audio import inspect_pcm16_wav
from llm_agent.models.capabilities import SpeechCapabilities
from llm_agent.models.types import SpeechRequest, SpeechResponse


class PiperSpeech:
    """只调用外部 Piper 服务，不创建语音模型子进程。"""

    provider_name = "piper"
    capabilities = SpeechCapabilities(
        wav_output=True, streaming=False, configurable_voice=True
    )

    def __init__(
        self,
        settings: dict | None = None,
        *,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        """从 models.yaml 构造客户端；允许环境变量临时覆盖 endpoint。"""
        settings = settings or {}
        self._endpoint = os.getenv(
            "PIPER_ENDPOINT", str(settings.get("endpoint", "http://127.0.0.1:8101"))
        ).rstrip("/")
        self._timeout = float(settings.get("timeout_seconds", 30))
        self._opener = opener

    def synthesize(self, request: SpeechRequest) -> SpeechResponse:
        """调用 ``POST /synthesize``，解码并验证服务返回的 PCM16 WAV。"""
        http_request = Request(
            f"{self._endpoint}/synthesize",
            data=json.dumps({"text": request.text}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(http_request, timeout=self._timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            if result.get("error"):
                raise RuntimeError(str(result["error"]))
            audio = base64.b64decode(result["audio_wav_base64"], validate=True)
            # 即便服务声明了采样率，也以实际 WAV 头为准，防止损坏音频下发。
            sample_rate, channels = inspect_pcm16_wav(audio)
        except Exception as error:
            raise RuntimeError(f"Piper service request failed: {error}") from error
        return SpeechResponse(
            audio_wav=audio,
            provider=str(result.get("provider", self.provider_name)),
            sample_rate=sample_rate,
            channels=channels,
        )
