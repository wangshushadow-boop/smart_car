"""Strongly typed Agent tools."""

from .registry import ToolRegistry
from .types import ToolCall, ToolResult

__all__ = ["ToolCall", "ToolRegistry", "ToolResult"]
