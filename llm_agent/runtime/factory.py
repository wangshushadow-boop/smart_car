"""根据配置装配 AgentRuntime 及其依赖。"""

from __future__ import annotations

from llm_agent.agent.graph import build_graph
from llm_agent.conversation import InMemoryConversationStore, NullConversationStore
from llm_agent.models.registry import select_backends

from .runtime import AgentRuntime


def create_runtime(config) -> tuple[AgentRuntime, str, str]:
    """创建 Runtime，并返回启动日志需要的实际 Provider 名称。"""
    generation, speech = select_backends(config)
    runtime_config = config.runtime
    if runtime_config.conversation_enabled:
        conversation_store = InMemoryConversationStore(
            max_turns=runtime_config.conversation_max_turns,
            max_context_chars=runtime_config.conversation_max_context_chars,
            ttl_seconds=runtime_config.conversation_ttl_seconds,
            max_sessions=runtime_config.conversation_max_sessions,
        )
    else:
        conversation_store = NullConversationStore()
    runtime = AgentRuntime(
        build_graph(model=generation, tts=speech),
        conversation_store=conversation_store,
    )
    return runtime, generation.provider_name, speech.provider_name
