"""Read-only robot status tool."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..context import ToolContext


class GetRobotStatusArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RobotStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    motion_state: str = "unknown"
    battery_percentage: float | None = Field(default=None, ge=0.0, le=100.0)
    fault: str | None = None
    detail: str = ""


class RobotStatusProvider(Protocol):
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
