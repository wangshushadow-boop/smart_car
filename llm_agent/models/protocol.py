"""Provider-independent model interface."""

from __future__ import annotations

from typing import Protocol

from .types import ModelRequest, ModelResponse


class ModelBackend(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        """Return one text completion for a typed multimodal request."""
