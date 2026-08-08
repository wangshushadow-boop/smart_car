"""Provider-independent generation and speech contracts."""

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
