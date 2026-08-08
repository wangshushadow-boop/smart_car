"""Whitelist registry responsible for validation and normalized failures."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError

from pydantic import ValidationError

from .context import ToolContext
from .protocol import AgentTool
from .types import ToolCall, ToolResult


class ToolRegistry:
    def __init__(self, default_timeout_seconds: float = 5.0) -> None:
        if default_timeout_seconds <= 0:
            raise ValueError("tool timeout must be positive")
        self._tools: dict[str, AgentTool] = {}
        self._default_timeout_seconds = default_timeout_seconds
        self._executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="llm-agent-tool"
        )

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def contains(self, name: str) -> bool:
        return name in self._tools

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                name=call.name,
                success=False,
                error=f"tool is not registered: {call.name}",
            )
        if context.cancelled.is_set():
            return ToolResult(name=call.name, success=False, error="request cancelled")
        try:
            arguments = tool.arguments_model.model_validate(call.arguments)
            timeout = float(
                getattr(tool, "timeout_seconds", self._default_timeout_seconds)
            )
            future = self._executor.submit(tool.execute, arguments, context)
            data = future.result(timeout=timeout)
            if not isinstance(data, dict):
                raise TypeError("tool result must be a dictionary")
            return ToolResult(name=call.name, success=True, data=data)
        except TimeoutError:
            future.cancel()
            return ToolResult(
                name=call.name,
                success=False,
                error=f"tool timed out after {timeout:g} seconds",
            )
        except ValidationError as error:
            return ToolResult(
                name=call.name,
                success=False,
                error=f"invalid tool arguments: {error}",
            )
        except Exception as error:
            return ToolResult(
                name=call.name,
                success=False,
                error=f"tool execution failed: {error}",
            )
