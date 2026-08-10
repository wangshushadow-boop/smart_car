"""Tool 调用与结果的通用数据契约。

`ToolCall` 是模型生成的 Tool 描述；`ToolResult` 是 `ToolRegistry` 归一化
后的执行结果。两者均使用 `extra="forbid"`，避免节点误传额外字段。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    """Tool 调用：`name` 命中 `ToolRegistry` 白名单，`arguments` 由 Tool 自校验。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Tool 执行结果。

    - `success=False` 时 `error` 必填，`data` 为空。
    - `success=True` 时 `data` 至少包含 `schema` 字段，便于后续节点判断产物类型
      （如 `MOTION_TASK_SCHEMA` 或 `MOTION_SEQUENCE_SCHEMA`）。
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    success: bool
    data: dict = Field(default_factory=dict)
    error: str | None = None
