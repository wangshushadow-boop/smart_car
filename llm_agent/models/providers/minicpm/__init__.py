"""本地 MiniCPM-o 推理 Provider 包。

通过本地 vLLM 暴露的 OpenAI 兼容 `/v1/chat/completions` 接口访问模型。
"""

from .generation import MiniCpmGeneration

__all__ = ["MiniCpmGeneration"]
