"""MiniMax synchronous cloud TTS using the official HTTP T2A endpoint."""

from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

from llm_agent.adapters.audio.wav import inspect_pcm16_wav

from ..capabilities import SpeechCapabilities
from ..types import SpeechRequest, SpeechResponse


class MiniMaxSpeech:
    provider_name = "minimax"
    capabilities = SpeechCapabilities(
        wav_output=True, streaming=False, configurable_voice=True
    )

    def __init__(self, settings: dict | None = None, opener=None) -> None:
        settings = settings or {}
        self._api_key = os.getenv("MINIMAX_API_KEY", "")
        if not self._api_key and opener is None:
            raise RuntimeError("MINIMAX_API_KEY is required for MiniMax speech")
        self._endpoint = os.getenv(
            "MINIMAX_SPEECH_URL",
            settings.get("speech_url", "https://api.minimax.io/v1/t2a_v2"),
        )
        self._model = os.getenv(
            "MINIMAX_SPEECH_MODEL",
            settings.get("speech_model", "speech-2.8-turbo"),
        )
        self._voice_id = os.getenv(
            "MINIMAX_VOICE_ID",
            settings.get(
                "voice_id", "Chinese (Mandarin)_Reliable_Executive"
            ),
        )
        self._sample_rate = int(settings.get("sample_rate", 32_000))
        self._timeout = float(settings.get("speech_timeout_seconds", 60))
        self._opener = opener or urlopen

    def synthesize(self, request: SpeechRequest) -> SpeechResponse:
        payload = {
            "model": self._model,
            "text": request.text,
            "stream": False,
            "language_boost": "Chinese",
            "output_format": "hex",
            "voice_setting": {
                "voice_id": self._voice_id,
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": self._sample_rate,
                "bitrate": 128_000,
                "format": "wav",
                "channel": 1,
            },
        }
        http_request = Request(
            self._endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener(http_request, timeout=self._timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise RuntimeError(f"MiniMax speech request failed: {error}") from error
        base_response = result.get("base_resp", {})
        if base_response.get("status_code", 0) != 0:
            raise RuntimeError(
                f"MiniMax speech failed: {base_response.get('status_msg', 'unknown error')}"
            )
        encoded_audio = result.get("data", {}).get("audio")
        if not encoded_audio:
            raise RuntimeError("MiniMax speech returned no audio")
        try:
            audio = bytes.fromhex(encoded_audio)
        except ValueError as error:
            raise RuntimeError("MiniMax speech returned invalid hex audio") from error
        sample_rate, channels = inspect_pcm16_wav(audio)
        return SpeechResponse(
            audio_wav=audio,
            provider=self.provider_name,
            sample_rate=sample_rate,
            channels=channels,
        )
