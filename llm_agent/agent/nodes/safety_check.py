"""Minimal whitelist check before a tool may execute."""

from __future__ import annotations

from llm_agent.tools.registry import ToolRegistry


def create_safety_check_node(registry: ToolRegistry):
    def safety_check(state: dict) -> dict:
        call = state.get("tool_call")
        if call is None:
            return {"error": "模型没有提供工具调用"}
        if not registry.contains(call.name):
            return {"error": f"工具未在白名单中：{call.name}"}
        return {}

    return safety_check
