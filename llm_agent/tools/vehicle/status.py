"""只读的车辆状态查询 Tool。

实际状态数据由 `RobotStatusProvider` 提供。当前默认实现是
`UnavailableRobotStatusProvider`，会在 ROS 状态网关接入前返回
`available=False`，避免 Agent 误以为有真实数据。
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..context import ToolContext


class GetRobotStatusArguments(BaseModel):
    """状态查询无入参；保留模型便于未来扩展（如查询维度过滤）。"""

    model_config = ConfigDict(extra="forbid")


class RobotStatus(BaseModel):
    """车辆状态快照；`available=False` 表示尚未接入真实数据源。"""

    model_config = ConfigDict(extra="forbid")

    available: bool
    motion_state: str = "unknown"
    battery_percentage: float | None = Field(default=None, ge=0.0, le=100.0)
    fault: str | None = None
    detail: str = ""


class RobotStatusProvider(Protocol):
    """由外部实现的实时状态读取协议（ROS 接入后由树莓派侧实现）。"""

    def get_status(self) -> RobotStatus:
        """Read a fresh status snapshot from the vehicle boundary."""


class UnavailableRobotStatusProvider:
    """Safe placeholder until the ROS gateway is introduced in phase 6."""

    def get_status(self) -> RobotStatus:
        return RobotStatus(
            available=False,
            detail="ROS 车辆状态网关尚未配置",
        )


class GetRobotStatusTool:
    """状态查询 Tool；通过注入 Provider 与底层状态网关解耦。"""

    name = "get_robot_status"
    description = "查询小车当前运动状态、电量和故障信息"
    arguments_model = GetRobotStatusArguments

    def __init__(self, provider: RobotStatusProvider | None = None) -> None:
        self._provider = provider or UnavailableRobotStatusProvider()

    def execute(
        self, arguments: GetRobotStatusArguments, context: ToolContext
    ) -> dict:
        del arguments, context
        return self._provider.get_status().model_dump(mode="json")
