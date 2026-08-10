"""Skill 调用、计划和结果类型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from llm_agent.tools.types import ToolCall, ToolResult


class SkillCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict = Field(default_factory=dict)


class SkillPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    tool_calls: list[ToolCall] = Field(min_length=1, max_length=8)


class SkillPlanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    success: bool
    tool_results: list[ToolResult] = Field(default_factory=list)
    error: str | None = None
