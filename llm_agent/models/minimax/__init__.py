"""MiniMax 云端推理与语音 Provider 包。

包含文本生成与 T2A v2 语音合成两路云端能力；均通过 `MINIMAX_API_KEY`
环境变量鉴权。需要时可通过 `select_backends()` 切换。
"""

from .generation import MiniMaxGeneration
from .speech import MiniMaxSpeech

__all__ = ["MiniMaxGeneration", "MiniMaxSpeech"]
