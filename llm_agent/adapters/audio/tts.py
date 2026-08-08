"""Text-to-speech boundary and Piper implementation."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from typing import Protocol


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str) -> bytes:
        """Return 16-bit PCM WAV audio."""


class PiperTts:
    def __init__(self) -> None:
        self._python = os.getenv("CAR_TTS_PYTHON", sys.executable)
        self._model = os.getenv(
            "CAR_TTS_MODEL",
            "/home/llm_agent/.local/share/piper/zh_CN-huayan-medium/zh_CN-huayan-medium.onnx",
        )
        self._config = os.getenv("CAR_TTS_CONFIG", self._model + ".json")

    def synthesize(self, text: str) -> bytes:
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
                input=text.encode("utf-8"),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
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
        return audio
