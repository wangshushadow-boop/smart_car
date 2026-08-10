"""文本到语音（TTS）的边界与 Piper 实现。

`PiperSpeech` 通过子进程调用本地 Piper ONNX 模型；`FallbackSpeech` 在
auto 模式下串联主备后端；`PiperTts` 是早期调用方期望的"字符串 → 字节"
接口兼容包装。所有实现都必须输出 ROS 能直接播放的 WAV（PCM16 单声道）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from llm_agent.adapters.audio.wav import inspect_pcm16_wav
from llm_agent.models.capabilities import SpeechCapabilities
from llm_agent.models.protocol import SpeechBackend
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
                "/home/llm_agent/.local/share/piper/zh_CN-huayan-medium/zh_CN-huayan-medium.onnx",
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


class FallbackSpeech:
    """优先尝试主后端，失败时回退到安全备后端。"""

    capabilities = SpeechCapabilities(
        wav_output=True, streaming=False, configurable_voice=True
    )

    def __init__(self, primary: SpeechBackend, fallback: SpeechBackend) -> None:
        self._primary = primary
        self._fallback = fallback
        self.provider_name = f"auto:{primary.provider_name}->{fallback.provider_name}"

    def synthesize(self, request: SpeechRequest) -> SpeechResponse:
        try:
            return self._primary.synthesize(request)
        except Exception:
            return self._fallback.synthesize(request)


class PiperTts:
    """为早期调用方提供的"字符串 → WAV bytes"接口兼容包装。"""

    def __init__(self, settings: dict | None = None) -> None:
        self._backend = PiperSpeech(settings)

    def synthesize(self, text: str) -> bytes:
        return self._backend.synthesize(SpeechRequest(text=text)).audio_wav


SpeechSynthesizer = SpeechBackend
