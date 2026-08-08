"""Agent graph: understand -> validate -> tool -> respond -> speech."""

from __future__ import annotations

from threading import Event

from langgraph.graph import END, START, StateGraph

from llm_agent.adapters.audio.tts import PiperTts, SpeechSynthesizer
from llm_agent.models.minicpm import MiniCpmModel
from llm_agent.models.protocol import ModelBackend
from llm_agent.tools.registry import ToolRegistry
from llm_agent.tools.vehicle.status import GetRobotStatusTool, RobotStatusProvider

from .nodes import (
    create_execute_tool_node,
    create_response_node,
    create_safety_check_node,
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
    cancelled: Event | None = None,
):
    model = model or MiniCpmModel()
    tts = tts or PiperTts()
    prompts = prompts or load_prompts()
    cancelled = cancelled or Event()
    if registry is None:
        registry = ToolRegistry()
        registry.register(GetRobotStatusTool(status_provider))

    graph = StateGraph(AgentState)
    graph.add_node("understand_intent", create_understand_node(model, prompts))
    graph.add_node("safety_check", create_safety_check_node(registry))
    graph.add_node("execute_tool", create_execute_tool_node(registry, cancelled))
    graph.add_node("generate_response", create_response_node(model, prompts))
    graph.add_node("synthesize_speech", create_speech_node(tts))

    graph.add_edge(START, "understand_intent")

    def route_intent(state: AgentState) -> str:
        decision = state["intent"]
        if decision.intent == IntentType.QUERY and state.get("tool_call"):
            return "safety_check"
        return "generate_response"

    graph.add_conditional_edges(
        "understand_intent",
        route_intent,
        {
            "safety_check": "safety_check",
            "generate_response": "generate_response",
        },
    )

    def route_safety(state: AgentState) -> str:
        return "generate_response" if state.get("error") else "execute_tool"

    graph.add_conditional_edges(
        "safety_check",
        route_safety,
        {
            "execute_tool": "execute_tool",
            "generate_response": "generate_response",
        },
    )
    graph.add_edge("execute_tool", "generate_response")
    graph.add_edge("generate_response", "synthesize_speech")
    graph.add_edge("synthesize_speech", END)
    return graph.compile()
