"""Agent Runtime 边界与生产依赖装配。"""

from __future__ import annotations

import json
from collections.abc import Callable
from threading import Event
from time import monotonic

from llm_agent.sessions import ConversationStore, NullConversationStore

from .contracts import (
    ContentPart,
    ContentType,
    RuntimeProgress,
    RuntimeRequest,
    RuntimeResponse,
)

ProgressCallback = Callable[[RuntimeProgress], None]


class AgentRuntime:
    """将 DialogueLoop、会话存储和统一响应投影封装成同步入口。"""

    def __init__(
        self,
        executor,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self._executor = executor
        self._conversation_store = conversation_store or NullConversationStore()
        self._stopping = Event()
        self._closed = False

    def stop(self) -> None:
        """停止新请求和后台任务，并释放持久化会话连接。"""
        self._stopping.set()
        stop = getattr(self._executor, "stop", None)
        if callable(stop):
            stop()
        if not self._closed:
            close = getattr(self._conversation_store, "close", None)
            if callable(close):
                close()
            self._closed = True

    def clear_conversation(self, session_id: str) -> None:
        self._conversation_store.clear(session_id)

    def run(
        self,
        request: RuntimeRequest,
        progress_callback: ProgressCallback | None = None,
        cancel_token: Event | None = None,
    ) -> RuntimeResponse:
        """执行一轮短对话；后台 Skill 不阻塞本次调用。"""
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
        report("queued", 0, "请求已进入 DialogueLoop")
        if cancel_token.is_set():
            return self._cancelled_response(request)
        history = self._conversation_store.recent(request.session_id)
        self._start_run(request)
        try:
            state = self._executor.invoke(
                {
                    "request_id": request.request_id,
                    "request": request,
                    "cancel_token": cancel_token,
                    "conversation_history": history,
                    "progress_callback": report,
                }
            )
        except Exception as error:
            self._finish_run(request.request_id, "failed", str(error))
            return self._error_response(request, "runtime_error", str(error))
        if cancel_token.is_set():
            self._finish_run(request.request_id, "cancelled", "请求已取消")
            return self._cancelled_response(request)

        answer = state.get("answer", "（无回复）")
        user_summary = state.get("user_summary") or self._request_text(request)
        self._conversation_store.append_turn(request.session_id, user_summary, answer)
        self._record_events(request.request_id, state.get("execution_trace", []))
        self._finish_run(
            request.request_id,
            "completed" if not state.get("error") else "partial_failure",
            state.get("error", ""),
        )
        outputs = [
            ContentPart(
                type=ContentType.TEXT,
                name="answer",
                mime_type="text/plain",
                text=answer,
            )
        ]
        if state.get("task"):
            outputs.append(
                ContentPart(
                    type=ContentType.JSON,
                    name="task",
                    mime_type="application/json",
                    text=json.dumps(
                        state["task"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
        report("completed", 100, "DialogueLoop 请求处理完成")
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
                "conversation_history_turns": len(history),
                "asr_provider": state.get("asr_backend", ""),
                "media_providers": state.get("media_providers", {}),
            },
        )

    def _start_run(self, request: RuntimeRequest) -> None:
        start_run = getattr(self._conversation_store, "start_run", None)
        if callable(start_run):
            start_run(request.request_id, request.session_id)

    def _finish_run(self, request_id: str, status: str, error: str = "") -> None:
        finish_run = getattr(self._conversation_store, "finish_run", None)
        if callable(finish_run):
            finish_run(request_id, status, error)

    def _record_events(self, request_id: str, events: list[dict]) -> None:
        record_events = getattr(self._conversation_store, "record_events", None)
        if callable(record_events):
            record_events(request_id, events)

    @staticmethod
    def _request_text(request: RuntimeRequest) -> str:
        return "\n".join(
            part.text.strip()
            for part in request.inputs
            if part.type in {ContentType.TEXT, ContentType.JSON} and part.text.strip()
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
        request: RuntimeRequest,
        code: str,
        message: str,
    ) -> RuntimeResponse:
        return RuntimeResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            status="failed",
            error_code=code,
            error_message=message,
        )


def create_runtime(
    config,
    robot_tool_executor=None,
    audio_output=None,
) -> tuple[AgentRuntime, str, str]:
    """装配唯一 Reactor、两个运行角色以及后台 TaskManager。"""
    from llm_agent.models.registry import check_required_model_services, select_backends
    from llm_agent.sessions import InMemoryConversationStore, SQLiteSessionStore
    from llm_agent.skills import MotionSequenceSkill, SkillRegistry, load_skill_directory
    from llm_agent.tools.policy import ToolPolicy
    from llm_agent.tools.registry import ToolRegistry
    from llm_agent.tools.vehicle import (
        CaptureCameraTool,
        GetRobotStatusTool,
        MoveRelativeTool,
        RotateRelativeTool,
        SetCameraPanTool,
        SetCameraTiltTool,
        StopMotionTool,
    )

    from .dialogue_loop import DialogueLoop
    from .prompt_builder import PromptBuilder
    from .reactor import Reactor
    from .skill_runner import SkillRunner
    from .task_manager import TaskManager

    check_required_model_services(config)
    generation, media, speech = select_backends(config)
    runtime_config = config.runtime
    if runtime_config.conversation_enabled:
        arguments = {
            "max_turns": runtime_config.conversation_max_turns,
            "max_context_chars": runtime_config.conversation_max_context_chars,
            "ttl_seconds": runtime_config.conversation_ttl_seconds,
            "max_sessions": runtime_config.conversation_max_sessions,
        }
        conversation_store = (
            SQLiteSessionStore(runtime_config.session_database_path, **arguments)
            if runtime_config.session_store == "sqlite"
            else InMemoryConversationStore(**arguments)
        )
    else:
        conversation_store = NullConversationStore()

    tools = ToolRegistry()
    tools.register(GetRobotStatusTool())
    tools.register(MoveRelativeTool(robot_tool_executor))
    tools.register(RotateRelativeTool(robot_tool_executor))
    tools.register(StopMotionTool(robot_tool_executor))
    if robot_tool_executor is not None:
        tools.register(SetCameraPanTool(robot_tool_executor))
        tools.register(SetCameraTiltTool(robot_tool_executor))
        tools.register(CaptureCameraTool(robot_tool_executor))

    skills = SkillRegistry()
    if runtime_config.skills_enabled:
        # Tool 只注册一次，SkillRegistry 仅创建不含执行逻辑的原子视图。
        skills.register_atomic_tools(tools)
        skills.register(MotionSequenceSkill())
        if robot_tool_executor is not None:
            load_skill_directory(skills, tools)

    reactor = Reactor(generation)
    prompt_builder = PromptBuilder(generation, skills)
    runner = SkillRunner(
        reactor=reactor,
        tools=tools,
        skills=skills,
        policy=ToolPolicy(tools),
        prompt_builder=prompt_builder,
        robot_tool_executor=robot_tool_executor,
        max_model_turns=runtime_config.agent_max_model_turns,
    )
    tasks = TaskManager(runner)
    dialogue = DialogueLoop(
        reactor=reactor,
        model=generation,
        speech=speech,
        skills=skills,
        task_manager=tasks,
        prompt_builder=prompt_builder,
        media=media,
        audio_output=audio_output,
    )
    runtime = AgentRuntime(
        dialogue,
        conversation_store=conversation_store,
    )
    return runtime, generation.provider_name, speech.provider_name
