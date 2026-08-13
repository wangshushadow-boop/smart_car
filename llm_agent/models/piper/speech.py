"""Piper 本地语音模型 Provider。"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from llm_agent.models.audio import inspect_pcm16_wav
from llm_agent.models.capabilities import SpeechCapabilities
from llm_agent.models.types import SpeechRequest, SpeechResponse


class PiperSpeech:
    """本地 Piper ONNX TTS；通过子进程隔离推理，避免污染主进程状态。"""

    provider_name = "piper"
    capabilities = SpeechCapabilities(
        wav_output=True, streaming=False, configurable_voice=True
    )

    def __init__(self, settings: dict | None = None) -> None:
        settings = settings or {}
        # 环境变量允许临时切换 Piper 解释器、模型与配置（调试或升级）。
        self._python = os.getenv(
            "CAR_TTS_PYTHON", settings.get("python", sys.executable)
        )
        self._model = os.getenv(
            "CAR_TTS_MODEL",
            settings.get(
                "model",
                "/mnt/d/AI/models/piper/zh_CN-huayan-medium/zh_CN-huayan-medium.onnx",
            ),
        )
        self._config = os.getenv(
            "CAR_TTS_CONFIG", settings.get("config", self._model + ".json")
        )
        self._timeout = float(settings.get("timeout_seconds", 30))

    def synthesize(self, request: SpeechRequest) -> SpeechResponse:
        """调用 Piper 合成 WAV，并校验采样率/声道数。"""
        output_path: str | None = None
        audio = b""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
                output_path = output_file.name
            subprocess.run(
                [
                    self._python,
                    "-m",
                    "piper",
                    "--model",
                    self._model,
                    "--config",
                    self._config,
                    "--output-file",
                    output_path,
                ],
                input=request.text.encode("utf-8"),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self._timeout,
            )
            with open(output_path, "rb") as output_file:
                audio = output_file.read()
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(f"Piper TTS failed: {error}") from error
        finally:
            # 不管成败都要清理临时文件，避免 /tmp 堆积。
            if output_path:
                try:
                    os.unlink(output_path)
                except FileNotFoundError:
                    pass
        if not audio:
            raise RuntimeError("Piper TTS returned an empty WAV")
        sample_rate, channels = inspect_pcm16_wav(audio)
        return SpeechResponse(
            audio_wav=audio,
            provider=self.provider_name,
            sample_rate=sample_rate,
            channels=channels,
        )
