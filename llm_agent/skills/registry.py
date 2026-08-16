"""Skill 白名单、参数校验和任务计划生成。

`SkillRegistry` 与 `ToolRegistry` 结构相似，但职责不同：
- Tool Registry 负责"单个原子动作"的参数校验与线程池执行。
- Skill Registry 负责高层参数校验，并生成固定计划或动态机器人任务。
"""

from __future__ import annotations

import hashlib
from typing import Literal, Protocol, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from llm_agent.tools.types import ToolCall


class AgentSkill(Protocol):
    """所有 Skill 共享的最小注册契约。"""

    name: str
    description: str
    arguments_model: Type[BaseModel]


class SkillCall(BaseModel):
    """模型生成且等待 Registry 校验的 Skill 调用。"""

    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict = Field(default_factory=dict)


class SkillPlan(BaseModel):
    """固定计划 Skill 展开后的原子 Tool 调用序列。"""

    model_config = ConfigDict(extra="forbid")
    name: str
    tool_calls: list[ToolCall] = Field(min_length=1, max_length=8)


class RobotTaskLimits(BaseModel):
    """动态机器人任务不可突破的 ReAct 执行预算。"""

    model_config = ConfigDict(extra="forbid")
    max_steps: int = Field(default=8, ge=1, le=30)
    timeout_seconds: float = Field(default=60.0, gt=0.0, le=300.0)
    max_total_rotation_deg: float = Field(default=180.0, ge=0.0, le=360.0)
    max_total_distance_m: float = Field(default=1.0, ge=0.0, le=5.0)


class RobotTask(BaseModel):
    """目录 Skill 生成的通用动态机器人任务。"""

    model_config = ConfigDict(extra="forbid")
    name: str
    goal: str
    instructions: str
    allowed_tools: list[str] = Field(min_length=1)
    limits: RobotTaskLimits = Field(default_factory=RobotTaskLimits)


class MotionSequenceStep(BaseModel):
    """组合运动中的单个直线或旋转步骤。"""

    model_config = ConfigDict(extra="forbid")
    action: Literal["move", "rotate"]
    distance_m: float | None = None
    direction: Literal["left", "right"] | None = None
    angle_deg: float | None = None

    @model_validator(mode="after")
    def validate_step(self) -> "MotionSequenceStep":
        if self.action == "move":
            if self.distance_m is None:
                raise ValueError("直线步骤必须提供 distance_m")
            if self.direction is not None or self.angle_deg is not None:
                raise ValueError("直线步骤不能包含旋转参数")
        else:
            if self.direction is None or self.angle_deg is None:
                raise ValueError("旋转步骤必须提供 direction 和 angle_deg")
            if self.distance_m is not None:
                raise ValueError("旋转步骤不能包含 distance_m")
        return self


class MotionSequenceArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[MotionSequenceStep] = Field(min_length=2, max_length=8)


class MotionSequenceSkill:
    """把确定的组合运动展开为顺序原子 Tool 调用。"""

    name = "motion_sequence"
    description = (
        "执行由 2 到 8 个明确直线或旋转步骤组成的组合运动；"
        "每步必须给出距离或左右方向与角度"
    )
    arguments_model = MotionSequenceArguments

    def plan(self, arguments: MotionSequenceArguments) -> SkillPlan:
        calls: list[ToolCall] = []
        for step in arguments.steps:
            if step.action == "move":
                calls.append(ToolCall(
                    name="move_relative",
                    arguments={"distance_m": step.distance_m},
                ))
            else:
                calls.append(ToolCall(
                    name="rotate_relative",
                    arguments={
                        "direction": step.direction,
                        "angle_deg": step.angle_deg,
                    },
                ))
        return SkillPlan(name=self.name, tool_calls=calls)


class SkillRegistry:
    """Skill 实例的统一注册与查找表。"""

    def __init__(self) -> None:
        self._skills: dict[str, AgentSkill] = {}

    def register(self, skill: AgentSkill) -> None:
        """注册 Skill；同名重复注册直接抛错。"""
        if skill.name in self._skills:
            raise ValueError(f"skill already registered: {skill.name}")
        self._skills[skill.name] = skill

    def contains(self, name: str) -> bool:
        """白名单查询；Agent Loop 用此快速拦截非法 Skill。"""
        return name in self._skills

    def is_reactive(self, name: str) -> bool:
        """判断 Skill 是否由通用观察-行动循环执行。"""
        skill = self._skills.get(name)
        return skill is not None and callable(getattr(skill, "create_task", None))

    def catalog_prompt(self) -> str:
        """只暴露简短目录，避免把所有 Skill 细节常驻模型上下文。"""
        if not self._skills:
            return ""
        lines = ["可用 Skill："]
        for skill in self._skills.values():
            lines.append(f"- {skill.name}: {skill.description}")
        return "\n".join(lines)

    def snapshot_id(self) -> str:
        """返回当前 Skill 摘要快照哈希，供 Session 记录任务运行时能力面。"""
        catalog = self.catalog_prompt().encode("utf-8")
        return hashlib.sha256(catalog).hexdigest()[:16]

    def plan(self, call: SkillCall) -> SkillPlan:
        """展开 Skill 调用：白名单校验 → 参数 Pydantic 校验 → 调用 `skill.plan()`。"""
        skill = self._skills.get(call.name)
        if skill is None:
            raise ValueError(f"skill is not registered: {call.name}")
        try:
            arguments = skill.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            raise ValueError(f"invalid skill arguments: {error}") from error
        planner = getattr(skill, "plan", None)
        if not callable(planner):
            raise ValueError(f"skill is not a planned skill: {call.name}")
        return planner(arguments)

    def create_task(self, call: SkillCall) -> RobotTask:
        """校验动态 Skill 参数并生成与执行器解耦的机器人任务。"""
        skill = self._skills.get(call.name)
        if skill is None:
            raise ValueError(f"skill is not registered: {call.name}")
        factory = getattr(skill, "create_task", None)
        if not callable(factory):
            raise ValueError(f"skill is not a reactive skill: {call.name}")
        try:
            arguments = skill.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            raise ValueError(f"invalid skill arguments: {error}") from error
        return factory(arguments)
