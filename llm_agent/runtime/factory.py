"""根据配置装配 AgentRuntime 及其依赖。"""

from __future__ import annotations

from llm_agent.agent.graph import build_graph
from llm_agent.models.registry import select_backends

from .runtime import AgentRuntime


def create_runtime(config) -> tuple[AgentRuntime, str, str]:
    """创建 Runtime，并返回启动日志需要的实际 Provider 名称。"""
    generation, speech = select_backends(config)
    runtime = AgentRuntime(build_graph(model=generation, tts=speech))
    return runtime, generation.provider_name, speech.provider_name
