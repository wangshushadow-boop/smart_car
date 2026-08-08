"""第一版 LangGraph：感知事件直接调用本地 MiniCPM-o。"""
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from .minicpm_client import MiniCpmClient


class AgentState(TypedDict, total=False):
    event: str
    speech_wav: bytes
    perception: dict
    answer: str
    answer_wav: bytes


def build_graph():
    client = MiniCpmClient()
    graph = StateGraph(AgentState)
    graph.add_node("ask_minicpm", client.respond)
    graph.add_edge(START, "ask_minicpm")
    graph.add_edge("ask_minicpm", END)
    return graph.compile()
