"""MiniMax 云端推理。

同时支持 MiniMax 的 OpenAI 与 Anthropic 兼容接口。Claude Code 常用的
``ANTHROPIC_*`` 环境变量可以直接复用；M3 的图片输入按兼容协议转换，
密钥仍只从进程环境读取。
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.request import Request, urlopen

from ...protocol import GenerationCapabilities, ModelRequest, ModelResponse


class MiniMaxGeneration:
    """MiniMax 云端生成 Provider。"""

    provider_name = "minimax"
    capabilities = GenerationCapabilities(
        text_input=True,
        image_input=True,
        audio_input=False,
        video_input=False,
        tool_calling=True,
        # MiniMax 推理模型会先生成 reasoning；预算过小可能在最终 JSON 前截断。
        response_max_tokens=2048,
        response_temperature=0.2,
    )

    def __init__(
        self,
        settings: dict | None = None,
        client: Any | None = None,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        settings = settings or {}
        inputs = set(settings.get("input", ["text", "image"]))
        self.capabilities = GenerationCapabilities(
            **{
                **type(self).capabilities.model_dump(),
                "text_input": "text" in inputs,
                "image_input": "image" in inputs,
                "audio_input": "audio" in inputs,
                "video_input": "video" in inputs,
                "response_max_tokens": settings.get("response_max_tokens", 2048),
                "response_temperature": settings.get("response_temperature", 0.2),
            }
        )
        self._reasoning_split = bool(settings.get("reasoning_split", True))
        self._timeout = float(settings.get("timeout_seconds", 90))
        self._opener = opener
        anthropic_base_url = os.getenv("ANTHROPIC_BASE_URL", "").rstrip("/")
        anthropic_api_key = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv(
            "ANTHROPIC_API_KEY", ""
        )
        self._protocol = str(settings.get("protocol", "openai")).lower()
        if client is None and (anthropic_base_url or self._protocol == "anthropic"):
            self._protocol = "anthropic"
            self._base_url = anthropic_base_url or str(
                settings.get("base_url", "https://api.minimaxi.com/anthropic")
            ).rstrip("/")
            self._api_key = anthropic_api_key or os.getenv("MINIMAX_API_KEY", "")
            if not self._api_key:
                raise RuntimeError(
                    "ANTHROPIC_AUTH_TOKEN, ANTHROPIC_API_KEY or MINIMAX_API_KEY "
                    "is required for MiniMax generation"
                )
            self._client = None
        else:
            self._protocol = "openai"
            base_url = os.getenv(
                "MINIMAX_BASE_URL",
                settings.get("base_url", "https://api.minimaxi.com/v1"),
            )
            # Token Plan keys are valid for both compatibility protocols. Accept
            # the Claude Code variable as a fallback so one secret can be reused.
            api_key = os.getenv("MINIMAX_API_KEY") or os.getenv(
                "ANTHROPIC_AUTH_TOKEN", ""
            )
            if client is None:
                if not api_key:
                    raise RuntimeError(
                        "MINIMAX_API_KEY is required for MiniMax generation"
                    )
                from openai import OpenAI

                client = OpenAI(
                    base_url=base_url,
                    api_key=api_key,
                    timeout=self._timeout,
                    max_retries=int(settings.get("max_retries", 1)),
                )
            self._client = client
        if self._protocol == "anthropic":
            model = (
                os.getenv("ANTHROPIC_MODEL")
                or os.getenv("MINIMAX_MODEL")
                or settings.get("model", "MiniMax-M3")
            )
        else:
            # Do not let Claude Code-specific model aliases override the OpenAI
            # endpoint. MINIMAX_MODEL is the explicit override for this path.
            model = os.getenv("MINIMAX_MODEL") or settings.get(
                "model", "MiniMax-M3"
            )
        self._model = str(model).strip().strip('"\'')

    def complete(self, request: ModelRequest) -> ModelResponse:
        """执行单次推理；多模态请求会被立刻抛错以避免静默丢失。"""
        unsupported = []
        if request.audio_data_urls:
            unsupported.append("audio")
        if request.video_data_urls:
            unsupported.append("video")
        if unsupported:
            names = ", ".join(unsupported)
            raise ValueError(f"MiniMax text API does not support: {names} input")
        if self._protocol == "anthropic":
            answer = self._complete_anthropic(request)
        else:
            answer = self._complete_openai(request)
        if not answer:
            raise RuntimeError("MiniMax returned no text")
        return ModelResponse(text=answer, provider=self.provider_name)

    def _complete_openai(self, request: ModelRequest) -> str | None:
        user_content: str | list[dict[str, Any]] = request.user_prompt
        if request.image_data_urls:
            user_content = [{"type": "text", "text": request.user_prompt}]
            user_content.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                }
                for image_url in request.image_data_urls
            )
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
                extra_body={"reasoning_split": self._reasoning_split},
            )
        except Exception as error:
            raise RuntimeError(f"MiniMax request failed: {error}") from error
        return next(
            (
                choice.message.content
                for choice in result.choices
                if getattr(choice.message, "content", None)
            ),
            None,
        )

    def _complete_anthropic(self, request: ModelRequest) -> str | None:
        user_content: str | list[dict[str, Any]] = request.user_prompt
        if request.image_data_urls:
            user_content = [{"type": "text", "text": request.user_prompt}]
            user_content.extend(
                _anthropic_image_block(image_url)
                for image_url in request.image_data_urls
            )
        payload = {
            "model": self._model,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": user_content}],
            "max_tokens": request.max_tokens,
            "temperature": max(0.01, min(request.temperature, 1.0)),
        }
        http_request = Request(
            f"{self._base_url}/v1/messages",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with self._opener(http_request, timeout=self._timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise RuntimeError(f"MiniMax request failed: {error}") from error
        return next(
            (
                block.get("text")
                for block in result.get("content", [])
                if block.get("type") == "text" and block.get("text")
            ),
            None,
        )


def _anthropic_image_block(image_url: str) -> dict[str, Any]:
    """把 Runtime 图片 URI 转成 Anthropic 兼容的 image content block。"""
    if image_url.startswith("data:") and ";base64," in image_url:
        header, data = image_url.split(";base64,", 1)
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": header.removeprefix("data:"),
                "data": data,
            },
        }
    return {
        "type": "image",
        "source": {"type": "url", "url": image_url},
    }
