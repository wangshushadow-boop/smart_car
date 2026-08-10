"""受约束的组合运动 Skill。

把"先左转 90 度，再前进 1 米"这样的多步任务，展开为原子 `move_relative` /
`rotate_relative` Tool 调用序列，由 `execute_skill` 节点串行执行。

约束：
- 必须 2–8 步，避免过长的运动序列堆在一次请求里。
- 每步要么是直线（`distance_m`），要么是旋转（`direction` + `angle_deg`）；
  模型用语义方向，正负号由对应 Tool 内部统一转换。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_agent.tools.types import ToolCall

from .types import SkillPlan


class MotionSequenceStep(BaseModel):
    """单步运动：模型使用语义方向，正负号由运动 Tool 统一转换。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["move", "rotate"]
    distance_m: float | None = None
    direction: Literal["left", "right"] | None = None
    angle_deg: float | None = None

    @model_validator(mode="after")
    def validate_step(self) -> "MotionSequenceStep":
        """按 `action` 互斥校验参数，避免出现半步运动 + 半步旋转的混合记录。"""
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
    """Skill 入参：2–8 个 MotionSequenceStep。"""

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
        """展开为顺序 Tool 调用列表。"""
        calls: list[ToolCall] = []
        for step in arguments.steps:
            if step.action == "move":
                # distance_m 正负由 Tool 内部允许范围统一约束（±2.0 米）。
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
