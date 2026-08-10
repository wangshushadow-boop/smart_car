"""Skill 调用、计划与结果的数据契约。

`SkillCall` 是模型生成的语义层参数；`SkillPlan` 是展开后的 Tool 调用列表；
`SkillPlanResult` 是执行结果汇总，供 LangGraph 节点投影到对外响应。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from llm_agent.tools.types import ToolCall, ToolResult


class SkillCall(BaseModel):
    """模型生成的 Skill 调用：`name` 必须命中 `SkillRegistry` 白名单。

    `arguments` 在 `SkillRegistry.plan()` 阶段会被对应 Skill 的
    `arguments_model` 进一步校验。
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict = Field(default_factory=dict)


class SkillPlan(BaseModel):
    """Skill 把高层参数展开后的 Tool 调用计划。

    `tool_calls` 长度限制为 1–8，与 `MotionSequenceArguments.steps` 对齐，
    保证单个组合任务不会撑爆执行队列。
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    tool_calls: list[ToolCall] = Field(min_length=1, max_length=8)


class SkillPlanResult(BaseModel):
    """Skill 执行结果：成功时 `error=None`，失败时填入首个失败 Tool 的错误。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    success: bool
    tool_results: list[ToolResult] = Field(default_factory=list)
    error: str | None = None
