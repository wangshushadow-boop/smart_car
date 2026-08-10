"""MiniMax 云端文本推理（仅支持文本）。

仅支持纯文本输入，多模态请求会被显式拒绝；本地意图节点不会触发这个
分支，只有 Chat 节点把多模态请求误路由到此处才会报错。
"""

from __future__ import annotations

import os
from typing import Any

from ..capabilities import GenerationCapabilities
from ..types import ModelRequest, ModelResponse


class MiniMaxGeneration:
    """MiniMax 文本推理 Provider。"""

    provider_name = "minimax"
    capabilities = GenerationCapabilities(
        text_input=True,
        image_input=False,
        audio_input=False,
        video_input=False,
        tool_calling=True,
    )

    def __init__(self, settings: dict | None = None, client: Any | None = None) -> None:
        settings = settings or {}
        base_url = os.getenv(
            "MINIMAX_BASE_URL", settings.get("base_url", "https://api.minimax.io/v1")
        )
        api_key = os.getenv("MINIMAX_API_KEY", "")
        if client is None:
            if not api_key:
                raise RuntimeError("MINIMAX_API_KEY is required for MiniMax generation")
            from openai import OpenAI

            client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=float(settings.get("timeout_seconds", 90)),
                max_retries=int(settings.get("max_retries", 1)),
            )
        self._client = client
        self._model = os.getenv(
            "MINIMAX_MODEL", settings.get("model", "MiniMax-M2.7")
        )

    def complete(self, request: ModelRequest) -> ModelResponse:
        """执行单次推理；多模态请求会被立刻抛错以避免静默丢失。"""
        unsupported = []
        if request.image_data_urls:
            unsupported.append("image")
        if request.audio_data_urls:
            unsupported.append("audio")
        if request.video_data_urls:
            unsupported.append("video")
        if unsupported:
            names = ", ".join(unsupported)
            raise ValueError(
                f"MiniMax OpenAI-compatible text API does not support: {names} input"
            )
        user_content = request.user_prompt
        try:
            result = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": user_content},
                ],
                max_completion_tokens=request.max_tokens,
                # MiniMax rejects 0 although it is useful for local intent models.
                temperature=max(0.01, min(request.temperature, 1.0)),
                extra_body={"reasoning_split": True},
            )
        except Exception as error:
            raise RuntimeError(f"MiniMax request failed: {error}") from error
        answer = next(
            (
                choice.message.content
                for choice in result.choices
                if getattr(choice.message, "content", None)
            ),
            None,
        )
        if not answer:
            raise RuntimeError("MiniMax returned no text")
        return ModelResponse(text=answer, provider=self.provider_name)
