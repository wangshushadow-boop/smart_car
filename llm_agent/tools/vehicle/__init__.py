"""白名单内的车辆 Tool 集合。

所有动作 Tool 只返回声明式任务（schema=`MOTION_TASK_SCHEMA`），不直接
访问 ROS 或硬件——真正的执行与二次安全校验在树莓派侧完成。新增 Tool 时
请遵循 `AgentTool` 协议并在此处 re-export。
"""

from .motion import (
    MOTION_TASK_SCHEMA,
    MoveRelativeTool,
    RotateRelativeTool,
    StopMotionTool,
)
from .status import GetRobotStatusTool, RobotStatus, RobotStatusProvider

__all__ = [
    "MOTION_TASK_SCHEMA",
    "GetRobotStatusTool",
    "MoveRelativeTool",
    "RobotStatus",
    "RobotStatusProvider",
    "RotateRelativeTool",
    "StopMotionTool",
]
