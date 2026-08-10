"""自动语音识别 Provider。"""

from .protocol import AsrBackend
from .qwen3 import Qwen3Asr
from .types import TranscriptionRequest, TranscriptionResponse

__all__ = [
    "AsrBackend",
    "Qwen3Asr",
    "TranscriptionRequest",
    "TranscriptionResponse",
]
