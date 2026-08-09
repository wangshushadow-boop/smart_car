"""Validated tool execution node."""

from __future__ import annotations

from llm_agent.tools.context import ToolContext
from llm_agent.tools.registry import ToolRegistry


def create_execute_tool_node(registry: ToolRegistry):
    def execute_tool(state: dict) -> dict:
        progress = state.get("progress_callback")
        if progress:
            progress("tool_running", 45, "正在执行白名单工具")
        call = state["tool_call"]
        result = registry.execute(
            call,
            ToolContext(
                request_id=state["request_id"],
                cancelled=state["cancel_token"],
                services={},
            ),
        )
        return {"tool_result": result}

    return execute_tool
