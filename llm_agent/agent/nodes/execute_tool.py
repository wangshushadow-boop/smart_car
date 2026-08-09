"""Validated tool execution node."""

from __future__ import annotations

from llm_agent.tools.context import ToolContext
from llm_agent.tools.registry import ToolRegistry
from llm_agent.tools.vehicle import MOTION_TASK_SCHEMA


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
        update = {"tool_result": result}
        # 动作工具只产生声明式任务。真正的 ROS 调用和第二次安全校验在树莓派执行。
        if result.success and result.data.get("schema") == MOTION_TASK_SCHEMA:
            update["command"] = result.data
        return update

    return execute_tool
