"""Provider 声明的能力集合（不可变）。

`GenerationCapabilities` 描述推理 Provider 支持的输入模态；调用方
`understand_intent` 等节点据此决定要不要把图像送进请求。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GenerationCapabilities(BaseModel):
    """推理 Provider 的输入能力与推荐生成参数。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text_input: bool = True
    image_input: bool = False
    audio_input: bool = False
    video_input: bool = False
    tool_calling: bool = False
    # 推理模型的思考 token 也可能计入输出上限。各 Provider 声明适合自身的
    # 意图识别预算，Agent 节点不再硬编码同一个值。
    intent_max_tokens: int = Field(default=160, ge=1, le=4096)
    intent_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    response_max_tokens: int = Field(default=256, ge=1, le=4096)
    response_temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class SpeechCapabilities(BaseModel):
    """语音 Provider 输出能力声明。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    wav_output: bool = True
    streaming: bool = False
    configurable_voice: bool = False
