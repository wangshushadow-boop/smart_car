"""Tool 实现契约。

`AgentTool` 是所有底盘 Tool 必须遵循的协议：声明名字、描述、参数模型，
并实现同步执行的 `execute`。返回值必须是 JSON 兼容 dict，便于 ROS 层
序列化到 `AgentContent`。
"""

from __future__ import annotations

from typing import Protocol, Type

from pydantic import BaseModel

from .context import ToolContext


class AgentTool(Protocol):
    name: str
    description: str
    arguments_model: Type[BaseModel]

    def execute(self, arguments: BaseModel, context: ToolContext) -> dict:
        """Execute a validated call and return JSON-compatible data."""
