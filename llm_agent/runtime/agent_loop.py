"""统一的模型—工具—观察 Agent Loop。

聊天、单步动作、固定计划 Skill 和动态机器人 Skill 都进入同一循环；模型每轮
只能选择一个 Skill 或返回最终答案。原子 Skill 在内部展开为唯一注册的 Tool，
参数、安全和预算分别委托给 Registry 与 ToolPolicy。
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_agent.models.protocol import (
    GenerationBackend,
    ModelRequest,
    SpeechBackend,
    SpeechRequest,
    TranscriptionRequest,
    parse_json_object,
    sanitize_spoken_answer,
)
from llm_agent.sessions import ConversationStore, NullConversationStore
from llm_agent.runtime.contracts import (
    ContentPart,
    ContentType,
    RuntimeProgress,
    RuntimeRequest,
    RuntimeResponse,
    model_inputs,
)
from llm_agent.skills import SkillCall, SkillRegistry
from llm_agent.tools.policy import ToolBudget, ToolPolicy
from llm_agent.tools.registry import ToolRegistry
from llm_agent.tools.types import ToolCall, ToolContext
from llm_agent.tools.vehicle import MOTION_TASK_SCHEMA

from .prompt_builder import PromptBuilder

_MODEL_OUTPUT_LOGGER = logging.getLogger("llm_agent.model_output")
_MOTION_SEQUENCE_SCHEMA = "small_car.motion_sequence.v1"

ProgressCallback = Callable[[RuntimeProgress], None]


@dataclass(frozen=True)
class PreparedMedia:
    """能力路由后的模型输入和本轮使用的媒体 Provider。"""

    text: str
    audio_urls: list[str]
    image_urls: list[str]
    video_urls: list[str]
    providers: dict[str, str]


class MediaRouter:
    """按主模型原生能力和有序 fallback 链理解入站媒体。"""

    def __init__(self, primary: GenerationBackend, routes=None) -> None:
        self._primary = primary
        self._routes = routes
        capabilities = primary.capabilities
        if routes is not None:
            self._native_inputs = set(routes.primary_inputs)
        else:
            self._native_inputs = {"text"}
            for modality in ("audio", "image", "video"):
                if getattr(capabilities, f"{modality}_input"):
                    self._native_inputs.add(modality)

    def prepare(
        self,
        text: str,
        audio_urls: list[str],
        image_urls: list[str],
        video_urls: list[str],
    ) -> PreparedMedia:
        """原生媒体保持不变；非原生媒体转换为带来源标记的文字块。"""
        blocks: list[str] = []
        providers: dict[str, str] = {}
        if audio_urls and "audio" not in self._native_inputs:
            value, provider = self._transcribe(audio_urls)
            blocks.append(f"[Audio transcript]\n{value}")
            providers["audio"] = provider
            audio_urls = []
        if image_urls and "image" not in self._native_inputs:
            values, provider = self._describe("image", image_urls)
            blocks.extend(
                f"<<UNTRUSTED_MEDIA type=image index={index}/{len(values)} "
                f"source=external>>\n{value}\n<<END_UNTRUSTED_MEDIA>>"
                for index, value in enumerate(values, start=1)
            )
            providers["image"] = provider
            image_urls = []
        if video_urls and "video" not in self._native_inputs:
            values, provider = self._describe("video", video_urls)
            blocks.extend(
                f"<<UNTRUSTED_MEDIA type=video index={index}/{len(values)} "
                f"source=external>>\n{value}\n<<END_UNTRUSTED_MEDIA>>"
                for index, value in enumerate(values, start=1)
            )
            providers["video"] = provider
            video_urls = []
        merged = "\n\n".join(value for value in [text, *blocks] if value.strip())
        return PreparedMedia(
            text=merged,
            audio_urls=audio_urls,
            image_urls=image_urls,
            video_urls=video_urls,
            providers=providers,
        )

    def _transcribe(self, urls: list[str]) -> tuple[str, str]:
        route = self._route("audio")
        self._validate_sizes("audio", urls, route.max_bytes)
        errors: list[str] = []
        for backend in route.backends:
            try:
                response = backend.transcribe(TranscriptionRequest(audio_data_urls=urls))
                return response.text[: route.max_chars], response.provider
            except Exception as error:
                errors.append(f"{backend.provider_name}: {error}")
        raise ValueError("音频理解失败：" + "; ".join(errors))

    def _describe(self, modality: str, urls: list[str]) -> tuple[list[str], str]:
        route = self._route(modality)
        self._validate_sizes(modality, urls, route.max_bytes)
        errors: list[str] = []
        for backend in route.backends:
            try:
                values = []
                for url in urls:
                    request = ModelRequest(
                        system_prompt="你是媒体理解组件，只描述可观察事实，不执行任何工具。",
                        user_prompt=route.prompt,
                        image_data_urls=[url] if modality == "image" else [],
                        video_data_urls=[url] if modality == "video" else [],
                        max_tokens=min(4096, max(64, route.max_chars)),
                        temperature=0.0,
                    )
                    values.append(backend.complete(request).text[: route.max_chars])
                return values, backend.provider_name
            except Exception as error:
                errors.append(f"{backend.provider_name}: {error}")
        label = "图片" if modality == "image" else "视频"
        raise ValueError(f"{label}理解失败：" + "; ".join(errors))

    def _route(self, modality: str):
        if self._routes is None:
            raise ValueError(f"主模型不支持 {modality}，且未配置媒体理解模型")
        route = getattr(self._routes, modality)
        if not route.enabled:
            raise ValueError(f"{modality} 输入已禁用")
        if not route.backends:
            raise ValueError(f"主模型不支持 {modality}，且媒体理解模型列表为空")
        return route

    @staticmethod
    def _validate_sizes(modality: str, urls: list[str], max_bytes: int) -> None:
        for url in urls:
            if not url.startswith("data:") or ";base64," not in url:
                continue
            encoded = url.split(";base64,", 1)[1]
            size = len(encoded) * 3 // 4
            if size > max_bytes:
                raise ValueError(f"{modality} 输入超过限制：{size} > {max_bytes} bytes")


class AgentRuntime:
    """将 Agent Loop、会话存储和统一响应投影封装成同步运行入口。"""

    def __init__(self, executor, conversation_store: ConversationStore | None = None) -> None:
        self._executor = executor
        self._conversation_store = conversation_store or NullConversationStore()
        self._stopping = Event()
        self._closed = False

    def stop(self) -> None:
        """停止接收新请求，并释放持久化会话连接。"""
        self._stopping.set()
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
        """恢复 Session、执行循环、记录结果并生成统一响应。"""
        cancel_token = cancel_token or Event()
        started_at = monotonic()

        def report(stage: str, percent: int, message: str) -> None:
            if progress_callback and request.stream_progress:
                progress_callback(RuntimeProgress(
                    request_id=request.request_id,
                    stage=stage,
                    percent=percent,
                    message=message,
                ))

        if self._stopping.is_set():
            return self._error_response(request, "stopping", "Agent 正在停止")
        report("queued", 0, "请求已进入 Agent 队列")
        if cancel_token.is_set():
            return self._cancelled_response(request)
        report("understanding", 10, "正在理解多模态输入")
        history = self._conversation_store.recent(request.session_id)
        start_run = getattr(self._conversation_store, "start_run", None)
        if callable(start_run):
            start_run(request.request_id, request.session_id)
        try:
            state = self._executor.invoke({
                "request_id": request.request_id,
                "request": request,
                "cancel_token": cancel_token,
                "conversation_history": history,
                "progress_callback": report,
            })
        except Exception as error:
            self._finish_run(request.request_id, "failed", str(error))
            return self._error_response(request, "runtime_error", str(error))
        if cancel_token.is_set():
            self._finish_run(request.request_id, "cancelled", "请求已取消")
            return self._cancelled_response(request)

        answer = state.get("answer", "（无回复）")
        user_summary = state.get("user_summary") or self._request_text(request)
        self._conversation_store.append_turn(request.session_id, user_summary, answer)
        record_events = getattr(self._conversation_store, "record_events", None)
        if callable(record_events):
            record_events(request.request_id, state.get("execution_trace", []))
        self._finish_run(
            request.request_id,
            "completed" if not state.get("error") else "partial_failure",
            state.get("error", ""),
        )
        outputs = [ContentPart(
            type=ContentType.TEXT,
            name="answer",
            mime_type="text/plain",
            text=answer,
        )]
        if state.get("command"):
            outputs.append(ContentPart(
                type=ContentType.JSON,
                name="robot_task",
                mime_type="application/json",
                text=json.dumps(state["command"], ensure_ascii=False, separators=(",", ":")),
            ))
        if state.get("answer_wav"):
            outputs.append(ContentPart(
                type=ContentType.AUDIO,
                name="answer_audio",
                mime_type="audio/wav",
                data=state["answer_wav"],
            ))
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
                "conversation_history_turns": len(history),
                "asr_provider": state.get("asr_backend", ""),
                "media_providers": state.get("media_providers", {}),
            },
        )

    def _finish_run(self, request_id: str, status: str, error: str = "") -> None:
        finish_run = getattr(self._conversation_store, "finish_run", None)
        if callable(finish_run):
            finish_run(request_id, status, error)

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
    def _error_response(request: RuntimeRequest, code: str, message: str) -> RuntimeResponse:
        return RuntimeResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            status="failed",
            error_code=code,
            error_message=message,
        )


class AgentDecision(BaseModel):
    """模型每轮唯一允许返回的结构化决策。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["skill_call", "final"]
    skill_name: str | None = None
    arguments: dict = Field(default_factory=dict)
    status: Literal["completed", "failed"] | None = None
    answer: str = ""
    reason: str = ""

    @model_validator(mode="after")
    def validate_shape(self) -> "AgentDecision":
        if self.type == "skill_call" and not self.skill_name:
            raise ValueError("skill_call 必须提供 skill_name")
        if self.type == "final" and (not self.status or not self.answer.strip()):
            raise ValueError("final 必须提供 status 和非空 answer")
        return self


class AgentLoop:
    """与传输层无关的单一 Agent 执行循环。"""

    def __init__(
        self,
        *,
        model: GenerationBackend,
        speech: SpeechBackend,
        tools: ToolRegistry,
        skills: SkillRegistry,
        policy: ToolPolicy,
        prompt_builder: PromptBuilder,
        media=None,
        robot_tool_executor=None,
        max_model_turns: int = 20,
    ) -> None:
        self._model = model
        self._speech = speech
        self._media_router = MediaRouter(model, media)
        self._tools = tools
        self._skills = skills
        self._policy = policy
        self._prompt_builder = prompt_builder
        self._robot_tool_executor = robot_tool_executor
        self._max_model_turns = max_model_turns

    def invoke(self, input: dict) -> dict:
        """兼容 Runtime 的执行器契约，返回可投影为统一响应的状态字典。"""
        request = input["request"]
        cancelled = input["cancel_token"]
        progress = input.get("progress_callback")
        history = input.get("conversation_history", [])
        user_text, audio_urls, image_urls, video_urls = model_inputs(request)
        state: dict = {"user_summary": user_text}

        trace: list[dict] = []
        budget = ToolBudget.start()
        task = None
        completed_skill = ""
        last_provider = ""
        legacy_commands: list[dict] = []
        context = ToolContext(
            request_id=request.request_id,
            cancelled=cancelled,
            services={},
        )

        for turn in range(1, self._max_model_turns + 1):
            if cancelled.is_set():
                return self._failure(state, "request cancelled")
            try:
                prepared = self._media_router.prepare(
                    user_text, audio_urls, image_urls, video_urls
                )
            except Exception as error:
                return self._failure(state, f"媒体输入处理失败：{error}")
            user_text = prepared.text
            audio_urls = prepared.audio_urls
            image_urls = prepared.image_urls
            video_urls = prepared.video_urls
            if prepared.providers:
                state["media_providers"] = {
                    **state.get("media_providers", {}),
                    **prepared.providers,
                }
                if "audio" in prepared.providers:
                    state["asr_backend"] = prepared.providers["audio"]
                state["user_summary"] = user_text
            if progress:
                progress(
                    "agent_running",
                    min(15 + turn * 3, 78),
                    f"Agent 正在进行第 {turn} 轮决策",
                )
            if not request.allow_tools or completed_skill:
                allowed_skills: list[str] | None = []
            elif task is not None:
                # 动态任务内部只能调用其白名单中的同名原子 Skill。
                allowed_skills = self._policy.allowed_tools(task)
            else:
                # None 表示展示全部顶层 Skill；空列表表示本轮禁止调用。
                allowed_skills = None
            try:
                response = self._model.complete(
                    self._prompt_builder.build(
                        user_text=user_text,
                        history=history,
                        allowed_skills=allowed_skills,
                        trace=trace,
                        task=task,
                        completed_skill=completed_skill,
                        audio_urls=audio_urls,
                        image_urls=image_urls,
                        video_urls=video_urls,
                    )
                )
                last_provider = response.provider
                _MODEL_OUTPUT_LOGGER.info(
                    "request_id=%s stage=agent_loop turn=%s provider=%s 完整输出：\n%s",
                    request.request_id,
                    turn,
                    response.provider,
                    response.text,
                )
                decision = AgentDecision.model_validate(parse_json_object(response.text))
            except Exception as error:
                return self._failure(state, f"Agent 决策解析失败：{error}")

            if decision.type == "final":
                answer = sanitize_spoken_answer(decision.answer)
                if completed_skill and decision.status == "failed":
                    # Tool/Skill 执行结果是任务状态的权威来源；模型在收尾阶段
                    # 只能组织文案，不能把已成功的动作改判为失败。
                    answer = f"{completed_skill} 已执行完成。"
                state.update(
                    answer=answer or "抱歉，我暂时无法给出有效回答。",
                    generation_backend=last_provider,
                    execution_trace=trace,
                    skill_snapshot=self._skills.snapshot_id(),
                )
                if decision.status == "failed" and not completed_skill:
                    state["error"] = decision.reason or "模型报告任务失败"
                break

            if not request.allow_tools:
                return self._failure(state, "本轮请求禁止调用 Skill")

            if decision.type == "skill_call":
                # 已完成的单步/固定计划 Skill 进入只读收尾阶段；即使模型再次
                # 请求同一动作也绝不重复执行，直接使用确定性结果结束。
                if completed_skill:
                    state.update(
                        answer=f"{completed_skill} 已执行完成。",
                        generation_backend=last_provider,
                        execution_trace=trace,
                        skill_snapshot=self._skills.snapshot_id(),
                    )
                    break
                skill_call = SkillCall(
                    name=decision.skill_name or "", arguments=decision.arguments
                )
                if not self._skills.contains(skill_call.name):
                    return self._failure(state, f"Skill 未注册：{skill_call.name}")
                if task is not None:
                    if not self._skills.is_atomic(skill_call.name):
                        return self._failure(
                            state, "动态任务执行中只能调用获授权的原子 Skill"
                        )
                    trace.append(
                        {
                            "kind": "skill",
                            "name": skill_call.name,
                            "mode": "atomic",
                            "parent": task.name,
                        }
                    )
                    error = self._execute_planned_skill(
                        skill_call,
                        context,
                        trace,
                        budget,
                        legacy_commands,
                        task=task,
                    )
                    if error:
                        return self._failure(state, error, trace)
                    self._collect_observations(request.request_id, image_urls)
                    continue
                if self._skills.is_reactive(skill_call.name):
                    try:
                        task = self._skills.create_task(skill_call)
                    except ValueError as error:
                        return self._failure(state, str(error))
                    trace.append(
                        {"kind": "skill", "name": task.name, "goal": task.goal}
                    )
                    continue
                trace.append(
                    {"kind": "skill", "name": skill_call.name, "mode": "planned"}
                )
                error = self._execute_planned_skill(
                    skill_call, context, trace, budget, legacy_commands
                )
                if error:
                    return self._failure(state, error, trace)
                self._collect_observations(request.request_id, image_urls)
                # 单步骤和固定计划 Skill 的全部 Tool 均成功即完成执行阶段；
                # 下一轮仅允许 final，不再把任何动作能力暴露给模型。
                completed_skill = skill_call.name
                continue
        else:
            return self._failure(state, "Agent 达到最大模型决策轮数", trace)

        if legacy_commands:
            state["command"] = (
                legacy_commands[0]
                if len(legacy_commands) == 1
                else {
                    "schema": _MOTION_SEQUENCE_SCHEMA,
                    "skill": task.name if task else completed_skill or "agent_loop",
                    "steps": legacy_commands,
                }
            )
        self._synthesize_speech(request, state, progress)
        return state

    def _execute_planned_skill(
        self,
        call: SkillCall,
        context: ToolContext,
        trace: list[dict],
        budget: ToolBudget,
        legacy_commands: list[dict],
        task=None,
    ) -> str | None:
        """执行确定性计划 Skill；每个原子 Tool 仍独立校验并按顺序执行。"""
        try:
            plan = self._skills.plan(call)
        except ValueError as error:
            return str(error)
        for tool_call in plan.tool_calls:
            policy_error = self._policy.validate(tool_call, budget, task)
            if policy_error:
                return f"Skill 工具策略拒绝：{policy_error}"
            result = self._tools.execute(tool_call, context)
            trace.append(
                {
                    "kind": "tool",
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "success": result.success,
                    "data": result.data,
                    "error": result.error,
                }
            )
            if not result.success:
                return result.error or "Skill 工具执行失败"
            self._policy.consume(tool_call, budget)
            if result.data.get("schema") == MOTION_TASK_SCHEMA:
                legacy_commands.append(result.data)
        return None

    def _collect_observations(self, request_id: str, image_urls: list[str]) -> None:
        """获取 Robot Gateway 返回的最新图片，作为下一轮模型观察。"""
        if self._robot_tool_executor is None:
            return
        for data in self._robot_tool_executor.take_observations(request_id):
            encoded = base64.b64encode(data).decode("ascii")
            image_urls.append(f"data:image/jpeg;base64,{encoded}")
        if len(image_urls) > 4:
            del image_urls[:-4]

    def _synthesize_speech(self, request, state: dict, progress) -> None:
        """按输出策略朗读最终回答；TTS 失败时始终保留文字结果。"""
        if not getattr(self._speech, "enabled", True):
            return
        explicitly_requested = ContentType.AUDIO in request.response_modalities
        auto = getattr(self._speech, "auto", "off")
        has_audio_input = any(part.type == ContentType.AUDIO for part in request.inputs)
        should_speak = (
            explicitly_requested
            or auto == "always"
            or (auto == "inbound" and has_audio_input)
        )
        if not should_speak:
            return
        answer = state["answer"].strip()
        min_chars = getattr(self._speech, "min_chars", 0)
        max_chars = getattr(self._speech, "max_chars", len(answer))
        if len(answer) < min_chars:
            return
        # 输出长度属于 Agent 行为策略；模型端点、音色、采样率仍由 models.yaml 控制。
        answer = answer[:max_chars]
        if progress:
            progress("synthesizing", 88, "正在生成语音输出")
        try:
            speech = self._speech.synthesize(SpeechRequest(text=answer))
            state["answer_wav"] = speech.audio_wav
            state["speech_backend"] = speech.provider
        except Exception as error:
            failure = f"语音合成失败：{error}"
            state["error"] = "；".join(filter(None, [state.get("error"), failure]))

    @staticmethod
    def _failure(
        state: dict, message: str, trace: list[dict] | None = None
    ) -> dict:
        """把任意循环错误归一化为安全、可直接回复用户的状态。"""
        return {
            **state,
            "answer": "任务未能完成，车辆已经停止继续执行。",
            "error": message,
            "execution_trace": trace or [],
        }


def create_runtime(config, robot_tool_executor=None) -> tuple[AgentRuntime, str, str]:
    """根据配置装配唯一 Agent Runtime 及其 Provider、Skill 和 Tool。"""
    from llm_agent.sessions import InMemoryConversationStore
    from llm_agent.models.registry import check_required_model_services, select_backends
    from llm_agent.sessions import SQLiteSessionStore
    from llm_agent.skills import MotionSequenceSkill, SkillRegistry, load_skill_directory
    from llm_agent.tools.vehicle import (
        CaptureCameraTool,
        GetRobotStatusTool,
        MoveRelativeTool,
        RotateRelativeTool,
        SetCameraPanTool,
        SetCameraTiltTool,
        StopMotionTool,
    )

    check_required_model_services(config)
    generation, media, speech = select_backends(config)
    runtime_config = config.runtime
    if runtime_config.conversation_enabled:
        store_arguments = {
            "max_turns": runtime_config.conversation_max_turns,
            "max_context_chars": runtime_config.conversation_max_context_chars,
            "ttl_seconds": runtime_config.conversation_ttl_seconds,
            "max_sessions": runtime_config.conversation_max_sessions,
        }
        conversation_store = (
            SQLiteSessionStore(runtime_config.session_database_path, **store_arguments)
            if runtime_config.session_store == "sqlite"
            else InMemoryConversationStore(**store_arguments)
        )
    else:
        conversation_store = NullConversationStore()

    tool_registry = ToolRegistry()
    tool_registry.register(GetRobotStatusTool())
    tool_registry.register(MoveRelativeTool(robot_tool_executor))
    tool_registry.register(RotateRelativeTool(robot_tool_executor))
    tool_registry.register(StopMotionTool(robot_tool_executor))
    if robot_tool_executor is not None:
        tool_registry.register(SetCameraPanTool(robot_tool_executor))
        tool_registry.register(SetCameraTiltTool(robot_tool_executor))
        tool_registry.register(CaptureCameraTool(robot_tool_executor))

    skill_registry = SkillRegistry()
    if runtime_config.skills_enabled:
        # Tool 只注册一次；SkillRegistry 自动创建同名的单步骤 Skill 视图。
        skill_registry.register_atomic_tools(tool_registry)
        skill_registry.register(MotionSequenceSkill())
        if robot_tool_executor is not None:
            load_skill_directory(skill_registry, tool_registry)

    loop = AgentLoop(
        model=generation,
        speech=speech,
        tools=tool_registry,
        skills=skill_registry,
        policy=ToolPolicy(tool_registry),
        prompt_builder=PromptBuilder(generation, skill_registry),
        media=media,
        robot_tool_executor=robot_tool_executor,
        max_model_turns=runtime_config.agent_max_model_turns,
    )
    runtime = AgentRuntime(loop, conversation_store=conversation_store)
    return runtime, generation.provider_name, speech.provider_name
