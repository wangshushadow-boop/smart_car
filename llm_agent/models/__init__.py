"""与 Provider 解耦的生成与语音契约包。

把协议、数据类型、能力声明集中 re-export，便于上层节点统一引用。
新增 Provider 时实现 `GenerationBackend` / `SpeechBackend`，并在此处
re-export。
"""

from .capabilities import GenerationCapabilities, SpeechCapabilities
from .protocol import GenerationBackend, ModelBackend, SpeechBackend
from .types import ModelRequest, ModelResponse, SpeechRequest, SpeechResponse

__all__ = [
    "GenerationBackend",
    "GenerationCapabilities",
    "ModelBackend",
    "ModelRequest",
    "ModelResponse",
    "SpeechBackend",
    "SpeechCapabilities",
    "SpeechRequest",
    "SpeechResponse",
]
