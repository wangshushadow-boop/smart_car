"""MiniCPM-o native speech through the local Omni WebSocket endpoint."""

from __future__ import annotations

import json
import os

from llm_agent.adapters.audio.wav import inspect_pcm16_wav

from ..capabilities import SpeechCapabilities
from ..types import SpeechRequest, SpeechResponse


class MiniCpmSpeech:
    provider_name = "minicpm"
    capabilities = SpeechCapabilities(
        wav_output=True, streaming=False, configurable_voice=False
    )

    def __init__(self, settings: dict | None = None, connector=None) -> None:
        settings = settings or {}
        self._endpoint = os.getenv(
            "MINICPM_OMNI_WS",
            settings.get(
                "speech_endpoint", "ws://127.0.0.1:8099/v1/audio/speech/stream"
            ),
        )
        self._model = os.getenv(
            "MINICPM_MODEL",
            settings.get("model", "/mnt/d/AI/models/MiniCPM-o-4_5-AWQ"),
        )
        self._timeout = float(settings.get("speech_timeout_seconds", 60))
        if connector is None:
            from websockets.sync.client import connect

            connector = connect
        self._connector = connector

    def synthesize(self, request: SpeechRequest) -> SpeechResponse:
        audio = bytearray()
        try:
            with self._connector(
                self._endpoint,
                proxy=None,
                max_size=None,
                open_timeout=self._timeout,
                close_timeout=5,
            ) as websocket:
                websocket.send(
                    json.dumps(
                        {
                            "type": "session.config",
                            "model": self._model,
                            "response_format": "wav",
                        }
                    )
                )
                websocket.send(
                    json.dumps(
                        {"type": "input.text", "text": request.text},
                        ensure_ascii=False,
                    )
                )
                websocket.send(json.dumps({"type": "input.done"}))
                while True:
                    message = websocket.recv(timeout=self._timeout)
                    if isinstance(message, bytes):
                        audio.extend(message)
                        continue
                    event = json.loads(message)
                    if event.get("type") == "error":
                        raise RuntimeError(
                            event.get("message", "MiniCPM native speech failed")
                        )
                    if event.get("type") == "session.done":
                        break
                websocket.send(json.dumps({"type": "session.close"}))
        except Exception as error:
            raise RuntimeError(f"MiniCPM native speech failed: {error}") from error
        sample_rate, channels = inspect_pcm16_wav(bytes(audio))
        return SpeechResponse(
            audio_wav=bytes(audio),
            provider=self.provider_name,
            sample_rate=sample_rate,
            channels=channels,
        )
