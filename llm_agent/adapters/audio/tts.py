"""Text-to-speech boundary and Piper implementation."""

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
    provider_name = "piper"
    capabilities = SpeechCapabilities(
        wav_output=True, streaming=False, configurable_voice=True
    )

    def __init__(self, settings: dict | None = None) -> None:
        settings = settings or {}
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
    """Try the preferred speech provider, then a configured safe fallback."""

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
    """Compatibility wrapper for callers expecting text -> WAV bytes."""

    def __init__(self, settings: dict | None = None) -> None:
        self._backend = PiperSpeech(settings)

    def synthesize(self, text: str) -> bytes:
        return self._backend.synthesize(SpeechRequest(text=text)).audio_wav


SpeechSynthesizer = SpeechBackend
