"""通过本地 OpenAI 兼容端点调用 MiniCPM-o 多模态推理。

模型侧支持文本/图片/音频/视频，但 `ModelRequest` 暂未暴露视频字段；通过
环境变量（`MINICPM_BASE_URL` 等）允许临时切换端点和超时，不修改代码。
"""

from __future__ import annotations

import os
from typing import Any

from ...protocol import GenerationCapabilities, ModelRequest, ModelResponse


class ModelBackendError(RuntimeError):
    """归一化的模型传输或响应错误（被 Runtime 捕获并转为失败响应）。"""


class MiniCpmGeneration:
    """MiniCPM-o 多模态推理 Provider。"""

    provider_name = "minicpm"
    capabilities = GenerationCapabilities(
        text_input=True,
        image_input=True,
        audio_input=True,
        # The service supports video, but ModelRequest does not expose it yet.
        video_input=True,
        tool_calling=False,
        response_max_tokens=256,
        response_temperature=0.2,
    )

    def __init__(self, settings: dict | None = None, client: Any | None = None) -> None:
        settings = settings or {}
        inputs = set(settings.get("input", ["text", "image", "audio", "video"]))
        self.capabilities = GenerationCapabilities(
            **{
                **type(self).capabilities.model_dump(),
                "text_input": "text" in inputs,
                "image_input": "image" in inputs,
                "audio_input": "audio" in inputs,
                "video_input": "video" in inputs,
                "response_max_tokens": settings.get("response_max_tokens", 256),
                "response_temperature": settings.get("response_temperature", 0.2),
            }
        )
        # 环境变量允许在不修改代码的情况下临时覆盖连接参数（方便本地切换端口）。
        base_url = os.getenv(
            "MINICPM_BASE_URL", settings.get("base_url", "http://127.0.0.1:8099/v1")
        )
        api_key = os.getenv("MINICPM_API_KEY", settings.get("api_key", "EMPTY"))
        timeout = float(
            os.getenv(
                "MINICPM_TIMEOUT_SECONDS", str(settings.get("timeout_seconds", 90))
            )
        )
        max_retries = int(
            os.getenv("MINICPM_MAX_RETRIES", str(settings.get("max_retries", 1)))
        )
        if client is None:
            # 延迟 import openai，避免 Provider 加载拖慢 Agent 启动。
            from openai import OpenAI

            client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
                max_retries=max_retries,
            )
        self._client = client
        self._model = os.getenv(
            "MINICPM_MODEL",
            settings.get("model", "/mnt/d/AI/models/MiniCPM-o-4_5-AWQ"),
        )

    def complete(self, request: ModelRequest) -> ModelResponse:
        """把多模态请求翻译为 OpenAI Chat Completions 的多模态 content 块。"""
        content: list[dict] = [{"type": "text", "text": request.user_prompt}]
        for image_url in request.image_data_urls:
            content.append(
                {"type": "image_url", "image_url": {"url": image_url}}
            )
        for audio_url in request.audio_data_urls:
            content.append(
                {
                    "type": "audio_url",
                    "audio_url": {"url": audio_url},
                }
            )
        for video_url in request.video_data_urls:
            content.append(
                {"type": "video_url", "video_url": {"url": video_url}}
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
        return ModelResponse(text=answer, provider=self.provider_name)
