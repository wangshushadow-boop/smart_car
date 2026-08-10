"""受约束的组合运动 Skill。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_agent.tools.types import ToolCall

from .types import SkillPlan


class MotionSequenceStep(BaseModel):
    """模型使用语义方向，正负号由运动 Tool 统一转换。"""

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
    """把多步自然语言运动任务编排为原子运动 Tool 调用。"""

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
                calls.append(
                    ToolCall(
                        name="move_relative",
                        arguments={"distance_m": step.distance_m},
                    )
                )
            else:
                calls.append(
                    ToolCall(
                        name="rotate_relative",
                        arguments={
                            "direction": step.direction,
                            "angle_deg": step.angle_deg,
                        },
                    )
                )
        return SkillPlan(name=self.name, tool_calls=calls)
