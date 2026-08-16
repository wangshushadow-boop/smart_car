"""统一 Agent Loop、Gateway 与 SQLite SessionStore 的核心回归测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Event

from llm_agent.gateway import AgentGateway
from llm_agent.models.protocol import (
    GenerationCapabilities,
    ModelResponse,
    SpeechCapabilities,
    SpeechResponse,
    TranscriptionResponse,
)
from llm_agent.models.registry import MediaBackends, MediaRoute
from llm_agent.runtime import ContentPart, ContentType, RuntimeRequest, RuntimeResponse
from llm_agent.runtime.agent_loop import AgentLoop
from llm_agent.runtime.prompt_builder import PromptBuilder
from llm_agent.sessions import SQLiteSessionStore
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


class FakeModel:
    provider_name = "fake-model"
    capabilities = GenerationCapabilities(image_input=True)

    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ModelResponse(text=next(self._responses), provider=self.provider_name)


class FakeSpeech:
    provider_name = "fake-speech"
    capabilities = SpeechCapabilities()

    def __init__(
        self, *, auto: str = "off", min_chars: int = 0, max_chars: int = 1000
    ) -> None:
        self.enabled = True
        self.auto = auto
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.requests = []

    def synthesize(self, request):
        self.requests.append(request)
        return SpeechResponse(
            audio_wav=b"RIFF-test",
            provider=self.provider_name,
            sample_rate=16_000,
            channels=1,
        )


class FakeAudioOutput:
    def __init__(self) -> None:
        self.calls = []

    def enqueue(self, **kwargs) -> None:
        self.calls.append(kwargs)


class FakeAsr:
    provider_name = "fake-asr"

    def transcribe(self, _request):
        return TranscriptionResponse(text="向前走", provider=self.provider_name)


class FakeVision:
    provider_name = "fake-vision"
    capabilities = GenerationCapabilities(image_input=True, video_input=True)

    def complete(self, _request):
        return ModelResponse(text="画面中有一个水瓶", provider=self.provider_name)


class BrokenVision(FakeVision):
    provider_name = "broken-vision"

    def complete(self, _request):
        raise RuntimeError("offline")


class FakeRobotExecutor:
    def __init__(self) -> None:
        self.calls = []
        self._observations = []

    def execute(self, tool_name, arguments, **kwargs):
        self.calls.append((tool_name, arguments, kwargs))
        if tool_name == "capture_camera":
            self._observations = [b"jpeg-observation"]
        return {
            "schema": "small_car.tool_result.v1",
            "executed": True,
            "tool_name": tool_name,
        }

    def take_observations(self, _task_id):
        values, self._observations = self._observations, []
        return values


def make_loop(
    model: FakeModel,
    robot: FakeRobotExecutor,
    media=None,
    speech=None,
    audio_output=None,
) -> AgentLoop:
    tools = ToolRegistry()
    tools.register(GetRobotStatusTool())
    tools.register(MoveRelativeTool(robot))
    tools.register(RotateRelativeTool(robot))
    tools.register(StopMotionTool(robot))
    tools.register(SetCameraPanTool(robot))
    tools.register(SetCameraTiltTool(robot))
    tools.register(CaptureCameraTool(robot))
    skills = SkillRegistry()
    skills.register_atomic_tools(tools)
    skills.register(MotionSequenceSkill())
    load_skill_directory(skills, tools)
    return AgentLoop(
        model=model,
        speech=speech or FakeSpeech(),
        tools=tools,
        skills=skills,
        policy=ToolPolicy(tools),
        prompt_builder=PromptBuilder(model, skills),
        media=media,
        robot_tool_executor=robot,
        audio_output=audio_output or FakeAudioOutput(),
    )


def make_request(text: str, request_id: str = "loop-test") -> RuntimeRequest:
    return RuntimeRequest(
        request_id=request_id,
        session_id="robot-main",
        source="test",
        inputs=[ContentPart(type=ContentType.TEXT, text=text)],
        response_modalities=[ContentType.TEXT],
    )


class AgentLoopRuntimeTest(unittest.TestCase):
    @staticmethod
    def _media_routes(*, audio=(), image=(), video=()) -> MediaBackends:
        return MediaBackends(
            primary_inputs=frozenset({"text"}),
            audio=MediaRoute(True, 1024 * 1024, 2000, "转写音频", tuple(audio)),
            image=MediaRoute(True, 1024 * 1024, 1000, "描述图片", tuple(image)),
            video=MediaRoute(True, 1024 * 1024, 1000, "描述视频", tuple(video)),
        )

    def test_single_loop_executes_tool_then_returns_final_answer(self) -> None:
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"move_relative",'
                '"arguments":{"distance_m":0.2},"reason":"前进"}',
                '{"type":"final","status":"completed",'
                '"answer":"已经前进二十厘米。","reason":"动作完成"}',
            ]
        )
        robot = FakeRobotExecutor()
        state = make_loop(model, robot).invoke(
            {
                "request": make_request("前进二十厘米"),
                "request_id": "loop-test",
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertEqual(state["answer"], "已经前进二十厘米。")
        self.assertEqual(len(robot.calls), 1)
        self.assertEqual(robot.calls[0][0], "move_relative")

    def test_completed_atomic_skill_is_not_executed_twice(self) -> None:
        """模型收尾时重复请求相同 Skill，也不能再次向 Robot Gateway 下发。"""
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"move_relative",'
                '"arguments":{"distance_m":0.3},"reason":"前进"}',
                '{"type":"skill_call","skill_name":"move_relative",'
                '"arguments":{"distance_m":0.3},"reason":"重复请求"}',
            ]
        )
        robot = FakeRobotExecutor()

        state = make_loop(model, robot).invoke(
            {
                "request": make_request("前进三十厘米"),
                "request_id": "loop-test",
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )

        self.assertEqual(len(robot.calls), 1)
        self.assertEqual(state["answer"], "move_relative 已执行完成。")

    def test_directory_skill_uses_same_loop_and_new_observation(self) -> None:
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"find_object",'
                '"arguments":{"target_name":"水瓶"},"reason":"开始搜索"}',
                '{"type":"skill_call","skill_name":"capture_camera",'
                '"arguments":{},"reason":"先观察"}',
                '{"type":"final","status":"completed",'
                '"answer":"已经找到水瓶。","reason":"画面中确认"}',
            ]
        )
        robot = FakeRobotExecutor()
        state = make_loop(model, robot).invoke(
            {
                "request": make_request("找到水瓶"),
                "request_id": "loop-test",
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertEqual(state["answer"], "已经找到水瓶。")
        self.assertEqual(robot.calls[0][0], "capture_camera")
        self.assertEqual(len(model.requests[-1].image_data_urls), 1)

    def test_skill_cannot_call_tool_outside_its_allowlist(self) -> None:
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"find_object",'
                '"arguments":{"target_name":"水瓶"},"reason":"开始"}',
                '{"type":"skill_call","skill_name":"get_robot_status",'
                '"arguments":{},"reason":"越权"}',
            ]
        )
        robot = FakeRobotExecutor()
        state = make_loop(model, robot).invoke(
            {
                "request": make_request("找到水瓶"),
                "request_id": "loop-test",
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertIn("未获当前任务授权", state["error"])
        self.assertEqual(robot.calls, [])

    def test_rotation_without_direction_is_rejected_before_gateway(self) -> None:
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"rotate_relative",'
                '"arguments":{"angle_deg":30},"reason":"方向不明确"}'
            ]
        )
        robot = FakeRobotExecutor()
        state = make_loop(model, robot).invoke(
            {
                "request": make_request("旋转三十度"),
                "request_id": "loop-test",
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertIn("必须明确指定", state["error"])
        self.assertEqual(robot.calls, [])

    def test_request_can_disable_all_tool_and_skill_calls(self) -> None:
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"move_relative",'
                '"arguments":{"distance_m":0.2},"reason":"尝试执行"}'
            ]
        )
        robot = FakeRobotExecutor()
        request = make_request("只讨论怎么前进，不要执行")
        request.allow_tools = False
        state = make_loop(model, robot).invoke(
            {
                "request": request,
                "request_id": "loop-test",
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertIn("禁止调用 Skill", state["error"])
        self.assertEqual(robot.calls, [])

    def test_planned_skill_executes_inside_the_same_loop(self) -> None:
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"motion_sequence",'
                '"arguments":{"steps":[{"action":"move","distance_m":0.2},'
                '{"action":"rotate","direction":"left","angle_deg":30}]},'
                '"reason":"执行组合动作"}',
                '{"type":"final","status":"completed",'
                '"answer":"组合动作已完成。","reason":"执行完成"}',
            ]
        )
        robot = FakeRobotExecutor()
        state = make_loop(model, robot).invoke(
            {
                "request": make_request("前进后左转"),
                "request_id": "loop-test",
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertEqual(state["answer"], "组合动作已完成。")
        self.assertEqual([call[0] for call in robot.calls], ["move_relative", "rotate_relative"])

    def test_audio_falls_back_to_configured_media_asr(self) -> None:
        model = FakeModel(
            ['{"type":"final","status":"completed","answer":"收到。","reason":"已转写"}']
        )
        robot = FakeRobotExecutor()
        request = RuntimeRequest(
            request_id="audio-test",
            source="test",
            inputs=[
                ContentPart(
                    type=ContentType.AUDIO,
                    mime_type="audio/wav",
                    data=b"RIFF-audio",
                )
            ],
        )
        state = make_loop(
            model,
            robot,
            self._media_routes(audio=(FakeAsr(),)),
        ).invoke(
            {
                "request": request,
                "request_id": request.request_id,
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertEqual(state["asr_backend"], "fake-asr")
        self.assertIn("向前走", model.requests[0].user_prompt)
        self.assertEqual(model.requests[0].audio_data_urls, [])

    def test_image_falls_back_to_media_model_without_silent_drop(self) -> None:
        model = FakeModel(
            ['{"type":"final","status":"completed","answer":"看到了。","reason":"已理解"}']
        )
        robot = FakeRobotExecutor()
        request = RuntimeRequest(
            request_id="image-test",
            source="test",
            inputs=[
                ContentPart(
                    type=ContentType.IMAGE,
                    mime_type="image/jpeg",
                    data=b"jpeg",
                )
            ],
        )
        make_loop(
            model,
            robot,
            self._media_routes(image=(FakeVision(),)),
        ).invoke(
            {
                "request": request,
                "request_id": request.request_id,
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertIn("画面中有一个水瓶", model.requests[0].user_prompt)
        self.assertEqual(model.requests[0].image_data_urls, [])

    def test_media_route_tries_backends_in_order(self) -> None:
        model = FakeModel(
            ['{"type":"final","status":"completed","answer":"看到了。","reason":"已理解"}']
        )
        request = RuntimeRequest(
            request_id="fallback-test",
            source="test",
            inputs=[ContentPart(type=ContentType.IMAGE, data=b"jpeg")],
        )
        state = make_loop(
            model,
            FakeRobotExecutor(),
            self._media_routes(image=(BrokenVision(), FakeVision())),
        ).invoke(
            {
                "request": request,
                "request_id": request.request_id,
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertEqual(state["media_providers"]["image"], "fake-vision")

    def test_unsupported_media_without_fallback_returns_explicit_error(self) -> None:
        model = FakeModel([])
        robot = FakeRobotExecutor()
        request = RuntimeRequest(
            request_id="video-test",
            source="test",
            inputs=[
                ContentPart(
                    type=ContentType.VIDEO,
                    mime_type="video/mp4",
                    data=b"video",
                )
            ],
        )
        state = make_loop(model, robot, self._media_routes()).invoke(
            {
                "request": request,
                "request_id": request.request_id,
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertIn("媒体理解模型列表为空", state["error"])

    def test_speech_off_only_honors_explicit_audio_request(self) -> None:
        model = FakeModel(
            ['{"type":"final","status":"completed","answer":"语音回答。","reason":"完成"}']
        )
        speech = FakeSpeech(auto="off")
        request = make_request("请回答")
        request.response_modalities.append(ContentType.AUDIO)
        state = make_loop(model, FakeRobotExecutor(), speech=speech).invoke(
            {
                "request": request,
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertEqual(len(speech.requests), 1)
        self.assertEqual(state["speech_backend"], "fake-speech")

    def test_speech_always_synthesizes_and_applies_length_limit(self) -> None:
        model = FakeModel(
            ['{"type":"final","status":"completed","answer":"一二三四五六","reason":"完成"}']
        )
        speech = FakeSpeech(auto="always", max_chars=4)
        audio_output = FakeAudioOutput()
        make_loop(
            model,
            FakeRobotExecutor(),
            speech=speech,
            audio_output=audio_output,
        ).invoke(
            {
                "request": make_request("请回答"),
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertEqual(speech.requests[0].text, "一二三四")
        self.assertEqual(audio_output.calls[0]["audio"], b"RIFF-test")
        self.assertEqual(audio_output.calls[0]["request_id"], "loop-test")

    def test_speech_inbound_only_synthesizes_for_audio_input(self) -> None:
        model = FakeModel(
            ['{"type":"final","status":"completed","answer":"收到。","reason":"完成"}']
        )
        speech = FakeSpeech(auto="inbound")
        request = RuntimeRequest(
            request_id="speech-inbound",
            source="test",
            inputs=[ContentPart(type=ContentType.AUDIO, data=b"RIFF-audio")],
        )
        make_loop(
            model,
            FakeRobotExecutor(),
            media=self._media_routes(audio=(FakeAsr(),)),
            speech=speech,
        ).invoke(
            {
                "request": request,
                "cancel_token": Event(),
                "conversation_history": [],
            }
        )
        self.assertEqual(len(speech.requests), 1)


class GatewayAndSessionTest(unittest.TestCase):
    def test_gateway_deduplicates_same_request_id(self) -> None:
        class FakeRuntime:
            def __init__(self) -> None:
                self.calls = 0

            def run(self, request, **_kwargs):
                self.calls += 1
                return RuntimeResponse(request_id=request.request_id, status="completed")

            def clear_conversation(self, _session_id):
                pass

            def stop(self):
                pass

        runtime = FakeRuntime()
        gateway = AgentGateway(runtime)
        request = make_request("你好", request_id="same-request")
        self.assertIs(gateway.run(request), gateway.run(request))
        self.assertEqual(runtime.calls, 1)

    def test_sqlite_session_survives_reopen_and_records_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            store.append_turn("session", "第一问", "第一答")
            store.start_run("request-1", "session")
            store.record_events("request-1", [{"kind": "tool", "name": "stop"}])
            store.finish_run("request-1", "completed")
            store.close()

            reopened = SQLiteSessionStore(path)
            turns = reopened.recent("session")
            reopened.close()
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].assistant_text, "第一答")


if __name__ == "__main__":
    unittest.main()
