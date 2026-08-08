"""MiniCPM-o backend using its local OpenAI-compatible endpoint."""

from __future__ import annotations

import base64
import os
from typing import Any

from .types import ModelRequest, ModelResponse


class ModelBackendError(RuntimeError):
    """Normalized model transport or response failure."""


class MiniCpmModel:
    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                base_url=os.getenv("MINICPM_BASE_URL", "http://127.0.0.1:8099/v1"),
                api_key=os.getenv("MINICPM_API_KEY", "EMPTY"),
                timeout=float(os.getenv("MINICPM_TIMEOUT_SECONDS", "90")),
                max_retries=int(os.getenv("MINICPM_MAX_RETRIES", "1")),
            )
        self._client = client
        self._model = os.getenv(
            "MINICPM_MODEL", "/mnt/d/AI/models/MiniCPM-o-4_5-AWQ"
        )

    def complete(self, request: ModelRequest) -> ModelResponse:
        content: list[dict] = [{"type": "text", "text": request.user_prompt}]
        if request.image_data_url:
            content.append(
                {"type": "image_url", "image_url": {"url": request.image_data_url}}
            )
        if request.speech_wav:
            encoded = base64.b64encode(request.speech_wav).decode("ascii")
            content.append(
                {"type": "audio_url", "audio_url": {"url": f"data:audio/wav;base64,{encoded}"}}
            )
        try:
            result = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": content},
                ],
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
        except Exception as error:
            raise ModelBackendError(f"MiniCPM request failed: {error}") from error
        answer = next(
            (
                choice.message.content
                for choice in result.choices
                if getattr(choice.message, "content", None)
            ),
            None,
        )
        if not answer:
            raise ModelBackendError("MiniCPM returned no text")
        return ModelResponse(text=answer)
