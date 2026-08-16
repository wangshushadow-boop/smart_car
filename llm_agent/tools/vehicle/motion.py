"""生成由树莓派本地执行的受约束运动任务。

三个 Tool 全部只产出声明式 JSON 任务，标注统一的 `MOTION_TASK_SCHEMA`：
- `MoveRelativeTool`：相对直线运动，正负号约定距离方向。
- `RotateRelativeTool`：相对旋转，优先使用显式 `direction`，兼容旧模型带符号角度。
- `StopMotionTool`：取消当前 Nav2 Action。
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..types import ToolContext


# 树莓派侧 Nav2 客户端据此判断任务类型；版本号 v1 兼容旧消息体。
MOTION_TASK_SCHEMA = "small_car.motion.v1"


class RobotToolExecutor(Protocol):
    def execute(
        self,
        tool_name: str,
        arguments: dict,
        *,
        task_id: str,
        cancelled,
        timeout_seconds: float = 20.0,
        request_observation: bool = False,
    ) -> dict: ...


class MoveRelativeArguments(BaseModel):
    """相对直线运动参数；正数向前，负数向后。"""

    model_config = ConfigDict(extra="forbid")

    # 距离边界 ±2.0 m：与控制律的稳定区间一致，超过会被直接拒绝。
    distance_m: float = Field(ge=-2.0, le=2.0)

    @field_validator("distance_m")
    @classmethod
    def reject_tiny_distance(cls, value: float) -> float:
        # 拒绝过小的位移，避免模型生成无意义的"微前进"。
        if abs(value) < 0.05:
            raise ValueError("移动距离的绝对值必须至少为 0.05 米")
        return value


class RotateRelativeArguments(BaseModel):
    """相对旋转参数；优先使用显式方向，并兼容旧的带符号角度。"""

    model_config = ConfigDict(extra="forbid")

    angle_deg: float = Field(ge=-180.0, le=180.0)
    direction: Literal["left", "right"] | None = None

    @field_validator("angle_deg")
    @classmethod
    def reject_tiny_angle(cls, value: float) -> float:
        if abs(value) < 1.0:
            raise ValueError("旋转角度的绝对值必须至少为 1 度")
        return value


class StopMotionArguments(BaseModel):
    """停止任务无入参；保留空模型便于未来扩展（如区域限制）。"""

    model_config = ConfigDict(extra="forbid")


class MoveRelativeTool:
    """只生成声明式任务，不在 Agent Server 上接触 ROS 或车辆硬件。"""

    name = "move_relative"
    description = "让小车相对前进或后退，单次距离不超过 2 米"
    arguments_model = MoveRelativeArguments
    timeout_seconds = 22.0

    def __init__(self, executor: RobotToolExecutor | None = None) -> None:
        self._executor = executor

    def execute(
        self, arguments: MoveRelativeArguments, context: ToolContext
    ) -> dict:
        if self._executor is not None:
            return self._executor.execute(
                self.name,
                {"distance_m": arguments.distance_m},
                task_id=context.request_id,
                cancelled=context.cancelled,
                timeout_seconds=20.0,
                request_observation=True,
            )
        del context
        return {
            "schema": MOTION_TASK_SCHEMA,
            "action": self.name,
            "distance_m": arguments.distance_m,
        }


class RotateRelativeTool:
    """生成相对旋转任务，具体速度和执行超时由树莓派决定。"""

    name = "rotate_relative"
    description = "让小车原地左转或右转，单次角度不超过 180 度"
    arguments_model = RotateRelativeArguments
    timeout_seconds = 22.0

    def __init__(self, executor: RobotToolExecutor | None = None) -> None:
        self._executor = executor

    def execute(
        self, arguments: RotateRelativeArguments, context: ToolContext
    ) -> dict:
        angle_deg = arguments.angle_deg
        # 显式方向消除模型对正负号约定的歧义；未提供时兼容旧模型。
        if arguments.direction == "left":
            angle_deg = abs(angle_deg)
        elif arguments.direction == "right":
            angle_deg = -abs(angle_deg)
        if self._executor is not None:
            return self._executor.execute(
                self.name,
                {"angle_deg": angle_deg},
                task_id=context.request_id,
                cancelled=context.cancelled,
                timeout_seconds=20.0,
                request_observation=True,
            )
        del context
        return {
            "schema": MOTION_TASK_SCHEMA,
            "action": self.name,
            "angle_deg": angle_deg,
        }


class StopMotionTool:
    """生成停止任务；树莓派收到后取消当前 Nav2 Action。"""

    name = "stop_motion"
    description = "取消小车当前正在执行的运动任务"
    arguments_model = StopMotionArguments
    timeout_seconds = 7.0

    def __init__(self, executor: RobotToolExecutor | None = None) -> None:
        self._executor = executor

    def execute(self, arguments: StopMotionArguments, context: ToolContext) -> dict:
        del arguments
        if self._executor is not None:
            return self._executor.execute(
                self.name,
                {},
                task_id=context.request_id,
                cancelled=context.cancelled,
                timeout_seconds=5.0,
            )
        del context
        return {"schema": MOTION_TASK_SCHEMA, "action": self.name}
