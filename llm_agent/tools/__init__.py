"""强类型 Agent Tool 包。

包含 Tool 协议、注册表与通用数据类型。具体的车辆相关 Tool 在
`llm_agent/tools/vehicle/` 子包；新增 Tool 时务必遵循 `AgentTool` 协议，
并通过 `ToolRegistry.register()` 加入白名单。
"""

from .registry import ToolRegistry
from .types import ToolCall, ToolResult

__all__ = ["ToolCall", "ToolRegistry", "ToolResult"]
