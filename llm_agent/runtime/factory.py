"""根据配置装配 AgentRuntime 及其依赖。

这是 `runtime/` 层的唯一公开入口，集中完成：
- 模型与 TTS 后端选择（`select_backends`）。
- 短期对话存储实例化（启用 / 空实现）。
- Skill 白名单构建（受 `skills_enabled` 控制）。
- LangGraph 编译并封装为可执行 Runtime。

返回值中包含 Provider 名称，方便启动日志提示当前实际启用的后端。
"""

from __future__ import annotations

from llm_agent.agent.graph import build_graph
from llm_agent.asr import Qwen3Asr
from llm_agent.conversation import InMemoryConversationStore, NullConversationStore
from llm_agent.models.registry import select_backends
from llm_agent.skills import MotionSequenceSkill, SkillRegistry

from .runtime import AgentRuntime


def create_runtime(config) -> tuple[AgentRuntime, str, str]:
    """创建 Runtime，并返回启动日志需要的实际 Provider 名称。

    参数：
        config: 已通过 Pydantic 校验的 `AgentConfig`。

    返回：
        (AgentRuntime, generation_provider_name, speech_provider_name)
        后两个字符串仅用于日志与诊断，不参与请求路由。
    """
    # 1. 选择推理与语音后端；`auto` 模式下内部会包装 FallbackSpeech。
    generation, speech = select_backends(config)
    runtime_config = config.runtime
    # 2. 短期对话存储：默认内存实现，受容量与 TTL 限制；关闭时换空实现。
    if runtime_config.conversation_enabled:
        conversation_store = InMemoryConversationStore(
            max_turns=runtime_config.conversation_max_turns,
            max_context_chars=runtime_config.conversation_max_context_chars,
            ttl_seconds=runtime_config.conversation_ttl_seconds,
            max_sessions=runtime_config.conversation_max_sessions,
        )
    else:
        conversation_store = NullConversationStore()
    # 3. Skill 白名单：当前只有 `motion_sequence` 一个受支持的高层任务。
    skill_registry = SkillRegistry()
    if runtime_config.skills_enabled:
        skill_registry.register(MotionSequenceSkill())
    # 4. 编译 LangGraph 并封装为 Runtime，供 ROS Action Server 注入。
    runtime = AgentRuntime(
        build_graph(
            model=generation,
            tts=speech,
            skill_registry=skill_registry,
            asr=Qwen3Asr(),
        ),
        conversation_store=conversation_store,
    )
    return runtime, generation.provider_name, speech.provider_name
