"""生成由树莓派本地执行的受约束运动任务。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..context import ToolContext


MOTION_TASK_SCHEMA = "small_car.motion.v1"


class MoveRelativeArguments(BaseModel):
    """相对直线运动参数；正数向前，负数向后。"""

    model_config = ConfigDict(extra="forbid")

    distance_m: float = Field(ge=-2.0, le=2.0)

    @field_validator("distance_m")
    @classmethod
    def reject_tiny_distance(cls, value: float) -> float:
        if abs(value) < 0.05:
            raise ValueError("移动距离的绝对值必须至少为 0.05 米")
        return value


class RotateRelativeArguments(BaseModel):
    """相对旋转参数；正数左转，负数右转。"""

    model_config = ConfigDict(extra="forbid")

    angle_deg: float = Field(ge=-180.0, le=180.0)

    @field_validator("angle_deg")
    @classmethod
    def reject_tiny_angle(cls, value: float) -> float:
        if abs(value) < 1.0:
            raise ValueError("旋转角度的绝对值必须至少为 1 度")
        return value


class StopMotionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoveRelativeTool:
    """只生成声明式任务，不在 Agent Server 上接触 ROS 或车辆硬件。"""

    name = "move_relative"
    description = "让小车相对前进或后退，单次距离不超过 2 米"
    arguments_model = MoveRelativeArguments

    def execute(
        self, arguments: MoveRelativeArguments, context: ToolContext
    ) -> dict:
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

    def execute(
        self, arguments: RotateRelativeArguments, context: ToolContext
    ) -> dict:
        del context
        return {
            "schema": MOTION_TASK_SCHEMA,
            "action": self.name,
            "angle_deg": arguments.angle_deg,
        }


class StopMotionTool:
    """生成停止任务；树莓派收到后取消当前 Nav2 Action。"""

    name = "stop_motion"
    description = "取消小车当前正在执行的运动任务"
    arguments_model = StopMotionArguments

    def execute(self, arguments: StopMotionArguments, context: ToolContext) -> dict:
        del arguments, context
        return {"schema": MOTION_TASK_SCHEMA, "action": self.name}
