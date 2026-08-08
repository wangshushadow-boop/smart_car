"""Lifecycle boundary around the compiled LangGraph."""

from __future__ import annotations

from threading import Event, Lock
from typing import Protocol

from .events import AgentEvent, event_from_legacy


class InvokableGraph(Protocol):
    def invoke(self, input: dict) -> dict:
        """Execute one graph turn."""


class AgentRuntime:
    """Serializes turns and owns the process-level cancellation signal."""

    def __init__(self, graph: InvokableGraph, cancelled: Event | None = None) -> None:
        self._graph = graph
        self._cancelled = cancelled or Event()
        self._turn_lock = Lock()

    @property
    def cancelled(self) -> Event:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled.set()

    def handle(self, value: AgentEvent | dict) -> dict:
        event = event_from_legacy(value)
        if self._cancelled.is_set():
            return {
                "request_id": event.request_id,
                "event": event,
                "error": "agent runtime is stopping",
                "answer": "Agent 正在停止，无法处理新的请求。",
            }
        with self._turn_lock:
            return self._graph.invoke(
                {"request_id": event.request_id, "event": event}
            )


def create_graph_handler(graph: InvokableGraph):
    """Backward-compatible callback adapter used by older callers."""

    runtime = AgentRuntime(graph)

    def handle(event_input: AgentEvent | dict) -> None:
        runtime.handle(event_input)

    return handle
