"""Agent 图的独立执行边界。

`AgentRuntime` 把 LangGraph 与对话存储封装成一次请求一个调用的同步入口，
方便 ROS Action Server、调试 Web、单元测试共享同一套编排。

关键约束：
- 不依赖 ROS 类型；传入的是纯领域对象 `RuntimeRequest`。
- 串行执行：`_turn_lock` 保证同一时刻只跑一轮 LangGraph，
  避免多 Goal 并发触发短期对话的竞态。
- 进度回调只接受 Runtime 自身定义的 `RuntimeProgress`，不泄漏 ROS 概念。
"""

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
    """LangGraph 编译产物的最小契约，便于测试注入假实现。"""

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
        # `_stopping` 用于优雅停机；`stop()` 后新请求直接被拒。
        self._stopping = Event()
        # 单轮锁：同一时刻只允许一个 Goal 走完整张图。
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
        """单轮入口：恢复历史 → 驱动 LangGraph → 写回历史 → 打包响应。"""
        cancel_token = cancel_token or Event()
        started_at = monotonic()

        def report(stage: str, percent: int, message: str) -> None:
            # 图内部 progress_callback 只关心 (阶段, 百分比, 文案)，
            # ROS 反馈由 transport 层负责包装。
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
                # 把 Runtime 内部的回调、取消令牌、历史一次性传给图节点。
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

            # 写回会话历史：纯文本形式，音频/图片不持久化。
            answer = state.get("answer", "（无回复）")
            user_summary = state.get("user_summary") or self._request_text(request)
            self._conversation_store.append_turn(
                request.session_id, user_summary, answer
            )

        # 把图内部 state 投影成统一的全模态 ContentPart 列表。
        outputs = [
            ContentPart(
                type=ContentType.TEXT,
                name="answer",
                mime_type="text/plain",
                text=answer,
            )
        ]
        if state.get("command"):
            # 声明式 ROS 任务（move/rotate/stop 或 motion_sequence 序列）。
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
        # 即使 answer 缺失，也走 completed 分支以兼容部分降级。
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
                "asr_provider": state.get("asr_backend", ""),
            },
        )

    @staticmethod
    def _request_text(request: RuntimeRequest) -> str:
        """从请求中提取纯文本输入，用于写回对话历史。"""
        return "\n".join(
            part.text.strip()
            for part in request.inputs
            if part.type in {ContentType.TEXT, ContentType.JSON}
            and part.text.strip()
        )

    @staticmethod
    def _cancelled_response(request: RuntimeRequest) -> RuntimeResponse:
        """被调用方取消后的标准响应。"""
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
        """统一的失败响应包装，确保 transport 层只需判断 status。"""
        return RuntimeResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            status="failed",
            error_code=code,
            error_message=message,
        )
