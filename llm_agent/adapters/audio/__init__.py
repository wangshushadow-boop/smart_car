"""与模型无关的音频适配器包。

包含 Piper 本地 TTS、WAV 校验、`FallbackSpeech` 包装器。`SpeechSynthesizer`
仅是 `SpeechBackend` 的类型别名，方便图装配时引用。
"""

from .tts import FallbackSpeech, PiperSpeech, PiperTts, SpeechSynthesizer

__all__ = ["FallbackSpeech", "PiperSpeech", "PiperTts", "SpeechSynthesizer"]
