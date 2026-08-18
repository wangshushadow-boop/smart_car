"""始终可响应用户输入的前台 DialogueLoop。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from llm_agent.models.protocol import (
    GenerationBackend,
    ModelRequest,
    SpeechBackend,
    SpeechRequest,
    TranscriptionRequest,
    sanitize_spoken_answer,
)
from llm_agent.skills import SkillCall, SkillRegistry

from .contracts import ContentType, model_inputs
from .prompt_builder import PromptBuilder
from .reactor import Reactor
from .task_manager import TaskManager, TaskRecord, TaskSubmission


@dataclass(frozen=True)
class PreparedMedia:
    """能力路由后的模型输入和实际使用的媒体 Provider。"""

    text: str
    audio_urls: list[str]
    image_urls: list[str]
    video_urls: list[str]
    providers: dict[str, str]


class MediaRouter:
    """仅负责把入站媒体转换成主模型可以理解的形式。"""

    def __init__(self, primary: GenerationBackend, routes=None) -> None:
        self._routes = routes
        if routes is not None:
            self._native_inputs = set(routes.primary_inputs)
        else:
            self._native_inputs = {"text"}
            for modality in ("audio", "image", "video"):
                if getattr(primary.capabilities, f"{modality}_input"):
                    self._native_inputs.add(modality)

    def prepare(
        self,
        text: str,
        audio_urls: list[str],
        image_urls: list[str],
        video_urls: list[str],
    ) -> PreparedMedia:
        """原生媒体保持不变，非原生媒体通过配置的 fallback 转成文字。"""
        blocks: list[str] = []
        providers: dict[str, str] = {}
        if audio_urls and "audio" not in self._native_inputs:
            value, provider = self._transcribe(audio_urls)
            blocks.append(f"[Audio transcript]\n{value}")
            providers["audio"] = provider
            audio_urls = []
        if image_urls and "image" not in self._native_inputs:
            values, provider = self._describe("image", image_urls)
            blocks.extend(self._untrusted("image", values))
            providers["image"] = provider
            image_urls = []
        if video_urls and "video" not in self._native_inputs:
            values, provider = self._describe("video", video_urls)
            blocks.extend(self._untrusted("video", values))
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
    def _untrusted(modality: str, values: list[str]) -> list[str]:
        return [
            f"<<UNTRUSTED_MEDIA type={modality} index={index}/{len(values)} "
            f"source=external>>\n{value}\n<<END_UNTRUSTED_MEDIA>>"
            for index, value in enumerate(values, start=1)
        ]

    @staticmethod
    def _validate_sizes(modality: str, urls: list[str], max_bytes: int) -> None:
        for url in urls:
            if not url.startswith("data:") or ";base64," not in url:
                continue
            encoded = url.split(";base64,", 1)[1]
            size = len(encoded) * 3 // 4
            if size > max_bytes:
                raise ValueError(
                    f"{modality} 输入超过限制：{size} > {max_bytes} bytes"
                )


class DialogueLoop:
    """完成一轮用户决策；长 Skill 交给 TaskManager 后立即返回。"""

    def __init__(
        self,
        *,
        reactor: Reactor,
        model: GenerationBackend,
        speech: SpeechBackend,
        skills: SkillRegistry,
        task_manager: TaskManager,
        prompt_builder: PromptBuilder,
        media=None,
        audio_output=None,
    ) -> None:
        self._reactor = reactor
        self._speech = speech
        self._skills = skills
        self._tasks = task_manager
        self._prompt_builder = prompt_builder
        self._media_router = MediaRouter(model, media)
        self._audio_output = audio_output
        self._speech_lock = Lock()
        self._tasks.add_completion_listener(self.handle_task_finished)

    def invoke(self, input: dict) -> dict:
        """理解一轮输入，并返回回答或后台任务受理结果。"""
        request = input["request"]
        cancelled = input["cancel_token"]
        progress = input.get("progress_callback")
        history = input.get("conversation_history", [])
        user_text, audio_urls, image_urls, video_urls = model_inputs(request)
        state: dict = {"user_summary": user_text}
        if cancelled.is_set():
            return self._failure(state, "request cancelled")
        try:
            prepared = self._media_router.prepare(
                user_text,
                audio_urls,
                image_urls,
                video_urls,
            )
            state["user_summary"] = prepared.text
            if prepared.providers:
                state["media_providers"] = prepared.providers
                if "audio" in prepared.providers:
                    state["asr_backend"] = prepared.providers["audio"]
            if progress:
                progress("dialogue_running", 30, "DialogueLoop 正在理解当前请求")
            decision, provider = self._reactor.decide(
                request_id=request.request_id,
                stage="dialogue_loop",
                turn=1,
                prompt=self._prompt_builder.build_dialogue(
                    user_text=prepared.text,
                    history=history,
                    allow_skills=request.allow_tools,
                    active_task=self._tasks.latest(request.session_id),
                    audio_urls=prepared.audio_urls,
                    image_urls=prepared.image_urls,
                    video_urls=prepared.video_urls,
                ),
            )
        except Exception as error:
            return self._failure(state, f"DialogueLoop 决策失败：{error}")

        state["generation_backend"] = provider
        state["skill_snapshot"] = self._skills.snapshot_id()
        if decision.type == "final":
            state["answer"] = sanitize_spoken_answer(decision.answer)
            if decision.status == "failed":
                state["error"] = decision.reason or "模型报告对话失败"
        elif decision.type == "task_control":
            if not request.allow_tools:
                return self._failure(state, "本轮请求禁止控制后台任务")
            cancelled_task = self._tasks.cancel_active()
            state["answer"] = (
                "已取消当前任务。" if cancelled_task else "当前没有正在执行的任务。"
            )
            state["execution_trace"] = [
                {"kind": "task_control", "action": "cancel"}
            ]
        else:
            if not request.allow_tools:
                return self._failure(state, "本轮请求禁止启动 Skill")
            call = SkillCall(
                name=decision.skill_name or "",
                arguments=decision.arguments,
            )
            if not self._skills.contains(call.name):
                return self._failure(state, f"Skill 未注册：{call.name}")
            snapshot = self._tasks.submit(
                TaskSubmission(
                    request=request,
                    skill_call=call,
                    image_urls=prepared.image_urls,
                )
            )
            state["answer"] = f"已开始执行 {call.name}。"
            state["task"] = snapshot.model_dump()
            state["execution_trace"] = [
                {"kind": "task_submit", "task_id": snapshot.task_id, "skill": call.name}
            ]
        self._synthesize_speech(request, state, progress, cancelled)
        return state

    def handle_task_finished(self, record: TaskRecord) -> None:
        """后台任务结束后主动播报，不依赖原 Service 调用方继续等待。"""
        self._synthesize_speech(
            record.submission.request,
            record.state,
            progress=None,
            cancelled=record.cancelled,
            request_id=record.task_id,
        )

    def stop(self) -> None:
        self._tasks.stop()

    def _synthesize_speech(
        self,
        request,
        state: dict,
        progress,
        cancelled,
        request_id: str | None = None,
    ) -> None:
        """根据统一输出策略合成并主动提交最终语音。"""
        if cancelled.is_set() or not getattr(self._speech, "enabled", True):
            return
        explicitly_requested = ContentType.AUDIO in request.response_modalities
        auto = getattr(self._speech, "auto", "off")
        has_audio_input = any(part.type == ContentType.AUDIO for part in request.inputs)
        if not (
            explicitly_requested
            or auto == "always"
            or (auto == "inbound" and has_audio_input)
        ):
            return
        answer = str(state.get("answer", "")).strip()
        if len(answer) < getattr(self._speech, "min_chars", 0):
            return
        answer = answer[: getattr(self._speech, "max_chars", len(answer))]
        if progress:
            progress("synthesizing", 88, "正在生成语音输出")
        try:
            # 部分 Provider 不是线程安全的，前台和后台播报在这里统一串行。
            with self._speech_lock:
                speech = self._speech.synthesize(SpeechRequest(text=answer))
            if self._audio_output is None:
                raise RuntimeError("未配置树莓派音频输出服务")
            self._audio_output.enqueue(
                request_id=request_id or request.request_id,
                audio=speech.audio_wav,
                mime_type="audio/wav",
            )
            state["speech_backend"] = speech.provider
        except Exception as error:
            failure = f"语音合成失败：{error}"
            state["error"] = "；".join(filter(None, [state.get("error"), failure]))

    @staticmethod
    def _failure(state: dict, message: str) -> dict:
        return {
            **state,
            "answer": "任务未能处理，车辆不会继续执行新动作。",
            "error": message,
            "execution_trace": [],
        }
