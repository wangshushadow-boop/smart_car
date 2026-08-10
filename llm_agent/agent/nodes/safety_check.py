"""Tool 执行前的最小白名单校验。

`ToolRegistry.validate()` 会再做参数级 Pydantic 校验，本节点只做"是否在
白名单"和"是否允许工具调用"的快速拦截，避免后续节点误执行。
"""

from __future__ import annotations

from llm_agent.tools.registry import ToolRegistry


def create_safety_check_node(registry: ToolRegistry):
    """构造 Tool 安全校验节点。"""

    def safety_check(state: dict) -> dict:
        progress = state.get("progress_callback")
        if progress:
            progress("safety_check", 35, "正在校验工具权限和参数")
        # 调用方通过 `allow_tools=False` 可彻底关停工具调用（例如调试或隐私模式）。
        if not state["request"].allow_tools:
            return {"error": "本轮请求禁止调用工具"}
        call = state.get("tool_call")
        if call is None:
            # 模型既没给 tool_call 也没给 skill_call，又被路由到这里，是路由逻辑漏洞。
            return {"error": "模型没有提供工具调用"}
        if not registry.contains(call.name):
            return {"error": f"工具未在白名单中：{call.name}"}
        # 通过校验：返回空 dict 让图继续往下走，不写 error 键。
        return {}

    return safety_check
