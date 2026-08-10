"""Agent 图的独立执行边界。"""

from __future__ import annotations

import json
from collections.abc import Callable
from threading import Event, Lock
from time import monotonic
from typing import Protocol

from llm_agent.conversation import ConversationStore, NullConversationStore

from .contracts import (
    ContentPart,
    ContentType,
    RuntimeProgress,
    RuntimeRequest,
    RuntimeResponse,
)


class InvokableGraph(Protocol):
    def invoke(self, input: dict) -> dict:
        """执行一轮 Agent 图。"""


ProgressCallback = Callable[[RuntimeProgress], None]


class AgentRuntime:
    """串行执行模型请求，并把图内部状态转换为统一响应。"""

    def __init__(
        self,
        graph: InvokableGraph,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self._graph = graph
        self._conversation_store = conversation_store or NullConversationStore()
        self._stopping = Event()
        self._turn_lock = Lock()

    def stop(self) -> None:
        """停止接收新请求；当前模型调用完成后退出。"""
        self._stopping.set()

    def clear_conversation(self, session_id: str) -> None:
        """清空指定短期会话，不影响其他客户端的 session。"""
        self._conversation_store.clear(session_id)

    def run(
        self,
        request: RuntimeRequest,
        progress_callback: ProgressCallback | None = None,
        cancel_token: Event | None = None,
    ) -> RuntimeResponse:
        cancel_token = cancel_token or Event()
        started_at = monotonic()

        def report(stage: str, percent: int, message: str) -> None:
            if progress_callback and request.stream_progress:
                progress_callback(
                    RuntimeProgress(
                        request_id=request.request_id,
                        stage=stage,
                        percent=percent,
                        message=message,
                    )
                )

        if self._stopping.is_set():
            return self._error_response(request, "stopping", "Agent 正在停止")
        report("queued", 0, "请求已进入 Agent 队列")
        with self._turn_lock:
            if cancel_token.is_set():
                return self._cancelled_response(request)
            report("understanding", 10, "正在理解多模态输入")
            conversation_history = self._conversation_store.recent(
                request.session_id
            )
            try:
                state = self._graph.invoke(
                    {
                        "request_id": request.request_id,
                        "request": request,
                        "cancel_token": cancel_token,
                        "conversation_history": conversation_history,
                        # 图节点只接收这个轻量回调，不需要了解 ROS Feedback 类型。
                        "progress_callback": report,
                    }
                )
            except Exception as error:
                return self._error_response(request, "runtime_error", str(error))
            if cancel_token.is_set():
                return self._cancelled_response(request)

            answer = state.get("answer", "（无回复）")
            user_summary = state.get("user_summary") or self._request_text(request)
            self._conversation_store.append_turn(
                request.session_id, user_summary, answer
            )

        outputs = [
            ContentPart(
                type=ContentType.TEXT,
                name="answer",
                mime_type="text/plain",
                text=answer,
            )
        ]
        if state.get("command"):
            outputs.append(
                ContentPart(
                    type=ContentType.JSON,
                    name="robot_task",
                    mime_type="application/json",
                    text=json.dumps(
                        state["command"], ensure_ascii=False, separators=(",", ":")
                    ),
                )
            )
        if state.get("answer_wav"):
            outputs.append(
                ContentPart(
                    type=ContentType.AUDIO,
                    name="answer_audio",
                    mime_type="audio/wav",
                    data=state["answer_wav"],
                )
            )
        report("completed", 100, "Agent 请求处理完成")
        return RuntimeResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            status="completed",
            outputs=outputs,
            generation_provider=state.get("generation_backend", ""),
            speech_provider=state.get("speech_backend", ""),
            error_code="partial_failure" if state.get("error") else "",
            error_message=state.get("error", ""),
            metadata={
                "elapsed_seconds": round(monotonic() - started_at, 3),
                "conversation_history_turns": len(conversation_history),
            },
        )

    @staticmethod
    def _request_text(request: RuntimeRequest) -> str:
        return "\n".join(
            part.text.strip()
            for part in request.inputs
            if part.type in {ContentType.TEXT, ContentType.JSON}
            and part.text.strip()
        )

    @staticmethod
    def _cancelled_response(request: RuntimeRequest) -> RuntimeResponse:
        return RuntimeResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            status="cancelled",
            error_code="cancelled",
            error_message="请求已取消",
        )

    @staticmethod
    def _error_response(
        request: RuntimeRequest, code: str, message: str
    ) -> RuntimeResponse:
        return RuntimeResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            status="failed",
            error_code=code,
            error_message=message,
        )
