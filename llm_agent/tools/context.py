"""Tool 可访问的受限依赖容器。

Tool 在执行期间只能从 `ToolContext` 里取需要的运行时信息；`request_id`
用于日志关联，`cancelled` 是取消令牌，`services` 用于注入 ROS Action
Client、状态网关等外部依赖（默认空 dict）。
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any


@dataclass(frozen=True)
class ToolContext:
    request_id: str
    cancelled: Event
    services: dict[str, Any]
