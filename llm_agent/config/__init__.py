"""Agent 配置加载与校验。

本模块定义 Agent 启动所需的全部配置模型（推理模型、输入输出模态、
运行时容量控制），并负责把 YAML 文件和环境变量统一转换为强类型的
`AgentConfig`。所有 Agent 入口（ROS Service Server、单元测试、命令行调试）
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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputModalitySelection(BaseModel):
    """一种入站媒体的理解模型链及资源边界。"""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    models: list[str] = Field(default_factory=list)
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    max_chars: int = Field(default=2000, ge=1, le=20_000)
    prompt: str = Field(default="请准确描述这段媒体内容。", min_length=1)


class InputModalities(BaseModel):
    """入站音频、图片和视频的统一能力路由。"""

    model_config = ConfigDict(extra="forbid")
    audio: InputModalitySelection = Field(
        default_factory=lambda: InputModalitySelection(
            models=["qwen3_asr"],
            max_bytes=20 * 1024 * 1024,
            max_chars=10_000,
            prompt="请转写这段音频。",
        )
    )
    image: InputModalitySelection = Field(
        default_factory=lambda: InputModalitySelection(
            models=["minicpm"],
            max_bytes=10 * 1024 * 1024,
            max_chars=1000,
            prompt="请准确描述图片中与用户请求相关的内容。",
        )
    )
    video: InputModalitySelection = Field(
        default_factory=lambda: InputModalitySelection(
            models=["minicpm"],
            max_bytes=50 * 1024 * 1024,
            max_chars=1500,
            prompt="请概括视频中与用户请求相关的事件。",
        )
    )


class AudioOutputSelection(BaseModel):
    """最终文字回答派生为语音时使用的策略和有序模型链。"""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    auto: Literal["off", "always", "inbound"] = "off"
    mode: Literal["final"] = "final"
    models: list[str] = Field(default_factory=lambda: ["piper"])
    min_chars: int = Field(default=2, ge=0, le=1000)
    max_chars: int = Field(default=1000, ge=1, le=20_000)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    failure: Literal["text_only"] = "text_only"

    @model_validator(mode="after")
    def validate_limits(self) -> "AudioOutputSelection":
        if self.enabled and not self.models:
            raise ValueError("启用音频输出时 models 不能为空")
        if len(self.models) != len(set(self.models)):
            raise ValueError("音频输出 models 不能包含重复模型")
        if self.min_chars > self.max_chars:
            raise ValueError("音频输出 min_chars 不能大于 max_chars")
        return self


class OutputModalities(BaseModel):
    """Agent 输出模态策略；文字始终作为主输出，不需要重复配置。"""

    model_config = ConfigDict(extra="forbid")
    audio: AudioOutputSelection = Field(default_factory=AudioOutputSelection)


class ModalitiesConfig(BaseModel):
    """按输入与输出方向组织的统一多模态配置。"""

    model_config = ConfigDict(extra="forbid")
    input: InputModalities = Field(default_factory=InputModalities)
    output: OutputModalities = Field(default_factory=OutputModalities)


class ModelConfig(BaseModel):
    """`models.yaml` 中一个可选择的模型实例。"""

    model_config = ConfigDict(extra="allow")
    backend: str = Field(min_length=1)
    roles: list[str] = Field(min_length=1)
    input: list[Literal["text", "image", "audio", "video"]] = Field(
        default_factory=list
    )
    # 由每个生成模型声明自身最大输出；只要求为正数，不设置统一上限。
    max_output_tokens: int | None = Field(default=None, ge=1)

    def settings(self) -> dict:
        payload = self.model_dump(exclude_none=True)
        payload.pop("backend", None)
        payload.pop("roles", None)
        return payload


class RuntimeConfig(BaseModel):
    """运行时容量与功能开关。

    所有数值边界（如 `max_inline_bytes >= 1024`）都在 Pydantic 校验阶段
    拒绝，避免运行时出现除零、内存爆等故障。
    """

    model_config = ConfigDict(extra="forbid")

    # 单次请求内联媒体上限，防止 ROS Service 携带过大文件拖垮总线。
    max_inline_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    # 是否启用 Skill 白名单；关闭后组合运动请求会直接降级为单步 Tool。
    skills_enabled: bool = True
    # 是否启用持久化或内存会话；关闭后统一替换为空实现。
    conversation_enabled: bool = True
    # 单会话最多保留的最近轮数。
    conversation_max_turns: int = Field(default=8, ge=1, le=100)
    # 拼到 Prompt 里的历史文本总字符上限，防止撑爆上下文窗口。
    conversation_max_context_chars: int = Field(default=12_000, ge=256)
    # 会话无活动多久后自动失效（秒）。
    conversation_ttl_seconds: float = Field(default=1800.0, gt=0)
    # 同时存在的最大会话数；超出后按最旧时间驱逐。
    conversation_max_sessions: int = Field(default=128, ge=1)
    # 生产使用 sqlite 持久化；memory 只用于临时调试和单元测试。
    session_store: Literal["sqlite", "memory"] = "sqlite"
    # SQLite 数据库不放在仓库，避免误提交运行数据。
    session_database_path: str = "~/.local/state/smart_car/agent_sessions.sqlite3"
    # 单次请求最多进行的模型—工具循环轮数，防止模型无限自循环。
    agent_max_model_turns: int = Field(default=20, ge=1, le=50)


class AgentConfig(BaseModel):
    """Agent 启动所需的完整配置聚合根。

    `models` 字典按实例名保存模型目录中的强类型配置，由 Provider 工厂解析。
    """

    model_config = ConfigDict(extra="forbid")

    generation_model: str = Field(default="minicpm", min_length=1)
    modalities: ModalitiesConfig = Field(default_factory=ModalitiesConfig)
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
    4. 应用生成模型与语音模型链的环境变量覆盖。
    """
    config_path = path or Path(
        os.getenv(
            "CAR_AGENT_CONFIG",
            str(Path(__file__).resolve().parent / "agent.yaml"),
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
    generation_model = os.getenv("CAR_GENERATION_MODEL")
    speech_models = os.getenv("CAR_SPEECH_MODELS")
    if generation_model:
        config.generation_model = generation_model
    if speech_models:
        config.modalities.output.audio.models = [
            name.strip() for name in speech_models.split(",") if name.strip()
        ]
        if not config.modalities.output.audio.models:
            raise ValueError("CAR_SPEECH_MODELS 至少需要一个模型名")
    return config
