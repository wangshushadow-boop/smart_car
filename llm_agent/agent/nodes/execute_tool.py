"""Validated tool execution node."""

from __future__ import annotations

from threading import Event

from llm_agent.tools.context import ToolContext
from llm_agent.tools.registry import ToolRegistry


def create_execute_tool_node(registry: ToolRegistry, cancelled: Event):
    def execute_tool(state: dict) -> dict:
        call = state["tool_call"]
        result = registry.execute(
            call,
            ToolContext(
                request_id=state["request_id"],
                cancelled=cancelled,
                services={},
            ),
        )
        return {"tool_result": result}

    return execute_tool
