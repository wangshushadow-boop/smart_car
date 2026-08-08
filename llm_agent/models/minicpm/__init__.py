"""Local MiniCPM-o generation and native speech providers."""

from .generation import MiniCpmGeneration, MiniCpmModel
from .speech import MiniCpmSpeech

__all__ = ["MiniCpmGeneration", "MiniCpmModel", "MiniCpmSpeech"]
