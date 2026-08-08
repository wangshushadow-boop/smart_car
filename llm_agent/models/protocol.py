"""Provider-independent model interface."""

from __future__ import annotations

from typing import Protocol

from .capabilities import GenerationCapabilities, SpeechCapabilities
from .types import ModelRequest, ModelResponse, SpeechRequest, SpeechResponse


class GenerationBackend(Protocol):
    @property
    def provider_name(self) -> str:
        """Stable provider identifier used in configuration and diagnostics."""

    @property
    def capabilities(self) -> GenerationCapabilities:
        """Declare supported request modalities before network access."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Return one text completion for a typed multimodal request."""


class SpeechBackend(Protocol):
    @property
    def provider_name(self) -> str:
        """Stable provider identifier used in configuration and diagnostics."""

    @property
    def capabilities(self) -> SpeechCapabilities:
        """Declare supported speech output features."""

    def synthesize(self, request: SpeechRequest) -> SpeechResponse:
        """Synthesize a validated WAV response from final answer text."""


# Compatibility name for the first architecture revision.
ModelBackend = GenerationBackend
