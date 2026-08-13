"""Agent 应用层配置加载与校验。

本模块定义 Agent 启动所需的全部配置模型（推理 Provider、语音 Provider、
运行时容量控制），并负责把 YAML 文件和环境变量统一转换为强类型的
`AgentConfig`。所有 Agent 入口（ROS Action Server、单元测试、命令行调试）
都通过 `load_agent_config()` 拿到同一份配置。

配置层级：
1. `agent.yaml`：模型选择与 Agent 行为。
2. `models.yaml`：模型、环境、端点和推理参数。
3. 环境变量：临时覆盖选择、配置路径或密钥。
4. Pydantic 模型：在加载阶段就拒绝非法值。
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class GenerationModelSelection(BaseModel):
    """生成模型实例选择。

    仅负责记录 Provider 名称；具体可用值由 `models/registry.py` 中的
    `ProviderRegistry` 在启动时校验。
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="minicpm", min_length=1)


class SpeechSelection(BaseModel):
    """语音 Provider 选择策略。

    `provider=auto` 时按照 `preferred` 优先尝试（可解析为 `native` 或
    `same_provider`，运行时映射为推理 Provider 名），失败或不可用时回退到
    `fallback`。显式指定 Provider 时不会静默回退。
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="auto", min_length=1)
    preferred: str = Field(default="same_provider", min_length=1)
    fallback: str = Field(default="piper", min_length=1)


class AsrSelection(BaseModel):
    """语音识别选择；auto 仅在生成模型不支持音频时启用 fallback。"""

    model_config = ConfigDict(extra="forbid")
    provider: str = Field(default="auto", min_length=1)
    fallback: str = Field(default="qwen3_asr", min_length=1)


class ModelConfig(BaseModel):
    """`models.yaml` 中一个可选择的模型实例。"""

    model_config = ConfigDict(extra="allow")
    backend: str = Field(min_length=1)
    roles: list[str] = Field(min_length=1)

    def settings(self) -> dict:
        payload = self.model_dump()
        payload.pop("backend", None)
        payload.pop("roles", None)
        return payload


class RuntimeConfig(BaseModel):
    """运行时容量与功能开关。

    所有数值边界（如 `max_inline_bytes >= 1024`）都在 Pydantic 校验阶段
    拒绝，避免运行时出现除零、内存爆等故障。
    """

    model_config = ConfigDict(extra="forbid")

    # 单次请求内联媒体上限，防止 ROS Action Goal 携带过大文件拖垮总线。
    max_inline_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    # 是否启用 Skill 白名单；关闭后组合运动请求会直接降级为单步 Tool。
    skills_enabled: bool = True
    # 是否启用短期多轮对话；关闭后 `InMemoryConversationStore` 替换为空实现。
    conversation_enabled: bool = True
    # 单会话最多保留的最近轮数。
    conversation_max_turns: int = Field(default=8, ge=1, le=100)
    # 拼到 Prompt 里的历史文本总字符上限，防止撑爆上下文窗口。
    conversation_max_context_chars: int = Field(default=12_000, ge=256)
    # 会话无活动多久后自动失效（秒）。
    conversation_ttl_seconds: float = Field(default=1800.0, gt=0)
    # 同时存在的最大会话数；超出后按最旧时间驱逐。
    conversation_max_sessions: int = Field(default=128, ge=1)


class AgentConfig(BaseModel):
    """Agent 启动所需的完整配置聚合根。

    `models` 字典按实例名保存模型目录中的强类型配置，由 Provider 工厂解析。
    """

    model_config = ConfigDict(extra="forbid")

    generation_model: GenerationModelSelection = Field(
        default_factory=GenerationModelSelection
    )
    asr: AsrSelection = Field(default_factory=AsrSelection)
    speech: SpeechSelection = Field(default_factory=SpeechSelection)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    models: dict[str, ModelConfig] = Field(default_factory=dict)


def load_agent_config(
    path: Path | None = None, models_path: Path | None = None
) -> AgentConfig:
    """加载并校验 Agent 配置。

    解析顺序：
    1. 解析路径：优先使用 `path`，否则读 `CAR_AGENT_CONFIG`，最后回退到
       `llm_agent/config/agent.yaml`。
    2. 从同目录或 `CAR_MODELS_CONFIG` 加载 `models.yaml`。
    3. 合并后通过 Pydantic 校验字段边界。
    4. 应用 generation model、ASR、speech 的环境变量覆盖。
    """
    config_path = path or Path(
        os.getenv(
            "CAR_AGENT_CONFIG",
            str(Path(__file__).resolve().parents[1] / "config" / "agent.yaml"),
        )
    )
    try:
        with config_path.open(encoding="utf-8") as config_file:
            payload = yaml.safe_load(config_file) or {}
    except OSError as error:
        raise RuntimeError(f"cannot load Agent config {config_path}: {error}") from error
    catalog_path = models_path or Path(
        os.getenv("CAR_MODELS_CONFIG", str(config_path.with_name("models.yaml")))
    )
    try:
        with catalog_path.open(encoding="utf-8") as models_file:
            models_payload = yaml.safe_load(models_file) or {}
    except OSError as error:
        raise RuntimeError(f"cannot load model config {catalog_path}: {error}") from error
    payload["models"] = models_payload.get("models", {})
    config = AgentConfig.model_validate(payload)
    # 环境变量用于临时切换 Provider，常用于本地调试或灰度。
    generation_model = os.getenv("CAR_GENERATION_MODEL") or os.getenv(
        "CAR_GENERATION_PROVIDER"
    )
    speech_provider = os.getenv("CAR_SPEECH_PROVIDER")
    asr_provider = os.getenv("CAR_ASR_PROVIDER")
    if generation_model:
        config.generation_model.provider = generation_model
    if speech_provider:
        config.speech.provider = speech_provider
    if asr_provider:
        config.asr.provider = asr_provider
    return config
