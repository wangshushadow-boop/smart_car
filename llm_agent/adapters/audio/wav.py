"""WAV validation shared by local and cloud speech providers."""

from __future__ import annotations

import io
import wave


def inspect_pcm16_wav(audio: bytes) -> tuple[int, int]:
    """Return sample rate and channels, rejecting output ROS cannot play safely."""

    if not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE":
        raise ValueError("speech output is not a WAV file")
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            if source.getsampwidth() != 2:
                raise ValueError("speech WAV must use 16-bit PCM")
            if source.getcomptype() != "NONE":
                raise ValueError("speech WAV must be uncompressed PCM")
            if source.getnframes() <= 0:
                raise ValueError("speech WAV has no frames")
            return source.getframerate(), source.getnchannels()
    except (EOFError, wave.Error) as error:
        raise ValueError(f"invalid speech WAV: {error}") from error
