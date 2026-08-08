"""Model-independent audio adapters."""

from .tts import FallbackSpeech, PiperSpeech, PiperTts, SpeechSynthesizer

__all__ = ["FallbackSpeech", "PiperSpeech", "PiperTts", "SpeechSynthesizer"]
