"""Provider 声明的能力集合（不可变）。

`GenerationCapabilities` 描述推理 Provider 支持的输入模态；调用方
`understand_intent` 等节点据此决定要不要把图像送进请求。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GenerationCapabilities(BaseModel):
    """推理 Provider 输入能力声明。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text_input: bool = True
    image_input: bool = False
    audio_input: bool = False
    video_input: bool = False
    tool_calling: bool = False


class SpeechCapabilities(BaseModel):
    """语音 Provider 输出能力声明。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    wav_output: bool = True
    streaming: bool = False
    configurable_voice: bool = False
