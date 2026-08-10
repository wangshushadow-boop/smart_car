"""本地与云端 TTS 共用的 WAV 校验工具。

ROS 音频播放路径要求 16-bit 非压缩 PCM 单声道；本函数在 TTS 输出后
立即检查，避免损坏的字节流下发到扬声器。
"""

from __future__ import annotations

import io
import wave


def inspect_pcm16_wav(audio: bytes) -> tuple[int, int]:
    """校验 WAV 头并返回 (采样率, 声道数)；任何不合规立即抛错。

    ROS 音频驱动只接受 16-bit 非压缩 PCM；这里同时校验帧数 > 0 以剔除
    静默失败的合成结果。
    """

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
