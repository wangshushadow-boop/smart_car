"""Agent 图：understand -> validate -> tool/skill -> respond -> speech。

图节点一览（按典型路径）：
- `understand_intent`     解析多模态请求，输出 IntentDecision + 可能的调用
- `safety_check`         单步 Tool 白名单校验（生成 error 或继续）
- `execute_tool`         线程池执行 Tool，产出声明式 command
- `skill_safety_check`   Skill 计划校验 + 每个 Tool 二次校验
- `execute_skill`        串行执行 Skill 内的 Tool
- `generate_response`    动作/Skill 走模板回复；其他走模型生成
- `synthesize_speech`    独立 TTS；失败不阻断文字结果

路由策略：
- 意图为 SKILL 且模型给出 skill_call → 走 Skill 分支。
- 意图为 QUERY/ACTION/CANCEL 且模型给出 tool_call → 走 Tool 分支。
- 其他（CHAT/UNKNOWN/无调用） → 直接生成回复。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from llm_agent.adapters.audio.tts import PiperSpeech, SpeechSynthesizer
from llm_agent.models.minicpm import MiniCpmModel
from llm_agent.models.protocol import ModelBackend
from llm_agent.skills import MotionSequenceSkill, SkillRegistry
from llm_agent.tools.registry import ToolRegistry
from llm_agent.tools.vehicle import (
    GetRobotStatusTool,
    MoveRelativeTool,
    RobotStatusProvider,
    RotateRelativeTool,
    StopMotionTool,
)

from .nodes import (
    create_execute_tool_node,
    create_execute_skill_node,
    create_response_node,
    create_safety_check_node,
    create_skill_safety_node,
    create_speech_node,
    create_understand_node,
)
from .prompt_loader import PromptSet, load_prompts
from .state import AgentState, IntentType


def build_graph(
    model: ModelBackend | None = None,
    tts: SpeechSynthesizer | None = None,
    registry: ToolRegistry | None = None,
    prompts: PromptSet | None = None,
    status_provider: RobotStatusProvider | None = None,
    skill_registry: SkillRegistry | None = None,
):
    """构造并编译 LangGraph。

    所有依赖都可由调用方显式注入，方便单元测试使用假实现；不传则走默认
    Provider（MiniCPM + Piper）和默认 Tool/Skill 白名单。

    返回值是可执行图（`CompiledStateGraph`），由 `AgentRuntime` 直接调用。
    """
    # 默认 Provider：本地 MiniCPM + Piper，便于独立启动进程。
    model = model or MiniCpmModel()
    tts = tts or PiperSpeech()
    prompts = prompts or load_prompts()
    # Tool 白名单：4 个声明式底盘 Tool，全部由树莓派侧二次校验后真正执行。
    if registry is None:
        registry = ToolRegistry()
        registry.register(GetRobotStatusTool(status_provider))
        registry.register(MoveRelativeTool())
        registry.register(RotateRelativeTool())
        registry.register(StopMotionTool())
    # Skill 白名单：当前仅支持 motion_sequence。
    if skill_registry is None:
        skill_registry = SkillRegistry()
        skill_registry.register(MotionSequenceSkill())

    graph = StateGraph(AgentState)
    graph.add_node(
        "understand_intent",
        create_understand_node(model, prompts, skill_registry.catalog_prompt()),
    )
    graph.add_node("safety_check", create_safety_check_node(registry))
    graph.add_node("execute_tool", create_execute_tool_node(registry))
    graph.add_node(
        "skill_safety_check", create_skill_safety_node(skill_registry, registry)
    )
    graph.add_node("execute_skill", create_execute_skill_node(registry))
    graph.add_node("generate_response", create_response_node(model, prompts))
    graph.add_node("synthesize_speech", create_speech_node(tts))

    graph.add_edge(START, "understand_intent")

    def route_intent(state: AgentState) -> str:
        """意图 → 三分支：Skill 计划、单步 Tool、直接回复。"""
        decision = state["intent"]
        if decision.intent == IntentType.SKILL and state.get("skill_call"):
            return "skill_safety_check"
        if decision.intent in {
            IntentType.QUERY,
            IntentType.ACTION,
            IntentType.CANCEL,
        } and state.get("tool_call"):
            return "safety_check"
        return "generate_response"

    graph.add_conditional_edges(
        "understand_intent",
        route_intent,
        {
            "safety_check": "safety_check",
            "skill_safety_check": "skill_safety_check",
            "generate_response": "generate_response",
        },
    )

    def route_safety(state: AgentState) -> str:
        """校验失败时回到 generate_response 给出安全回复，不让车动。"""
        return "generate_response" if state.get("error") else "execute_tool"

    graph.add_conditional_edges(
        "safety_check",
        route_safety,
        {
            "execute_tool": "execute_tool",
            "generate_response": "generate_response",
        },
    )
    graph.add_conditional_edges(
        "skill_safety_check",
        route_safety,
        {
            "execute_tool": "execute_skill",
            "generate_response": "generate_response",
        },
    )
    # 动作/技能执行后无论成败都汇总到 generate_response，避免跳过语音合成。
    graph.add_edge("execute_tool", "generate_response")
    graph.add_edge("execute_skill", "generate_response")
    graph.add_edge("generate_response", "synthesize_speech")
    graph.add_edge("synthesize_speech", END)
    return graph.compile()
