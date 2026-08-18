"""DialogueLoop、SkillRunner、TaskManager 与 Gateway 的核心回归测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Event, Lock

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
from llm_agent.runtime.dialogue_loop import DialogueLoop
from llm_agent.runtime.prompt_builder import PromptBuilder
from llm_agent.runtime.reactor import Reactor
from llm_agent.runtime.skill_runner import SkillRunner
from llm_agent.runtime.task_manager import TaskManager
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
        self._lock = Lock()
        self.requests = []

    def complete(self, request):
        with self._lock:
            self.requests.append(request)
            return ModelResponse(text=next(self._responses), provider=self.provider_name)


class FakeSpeech:
    provider_name = "fake-speech"
    capabilities = SpeechCapabilities()

    def __init__(self, *, auto: str = "off", max_chars: int = 1000) -> None:
        self.enabled = True
        self.auto = auto
        self.min_chars = 0
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


class FakeRobotExecutor:
    def __init__(self, blocker: Event | None = None) -> None:
        self.calls = []
        self.started = Event()
        self._blocker = blocker
        self._observations = []

    def execute(self, tool_name, arguments, **kwargs):
        self.calls.append((tool_name, arguments, kwargs))
        self.started.set()
        if self._blocker is not None:
            self._blocker.wait(2)
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


def make_stack(
    model: FakeModel,
    robot: FakeRobotExecutor,
    *,
    media=None,
    speech=None,
    audio_output=None,
) -> tuple[DialogueLoop, TaskManager]:
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
    reactor = Reactor(model)
    prompts = PromptBuilder(model, skills)
    runner = SkillRunner(
        reactor=reactor,
        tools=tools,
        skills=skills,
        policy=ToolPolicy(tools),
        prompt_builder=prompts,
        robot_tool_executor=robot,
    )
    tasks = TaskManager(runner)
    dialogue = DialogueLoop(
        reactor=reactor,
        model=model,
        speech=speech or FakeSpeech(),
        skills=skills,
        task_manager=tasks,
        prompt_builder=prompts,
        media=media,
        audio_output=audio_output or FakeAudioOutput(),
    )
    return dialogue, tasks


def make_request(text: str, request_id: str = "loop-test") -> RuntimeRequest:
    return RuntimeRequest(
        request_id=request_id,
        session_id="robot-main",
        source="test",
        inputs=[ContentPart(type=ContentType.TEXT, text=text)],
        response_modalities=[ContentType.TEXT],
    )


def invoke(dialogue: DialogueLoop, request: RuntimeRequest) -> dict:
    return dialogue.invoke(
        {
            "request": request,
            "request_id": request.request_id,
            "cancel_token": Event(),
            "conversation_history": [],
        }
    )


class DialogueAndSkillRuntimeTest(unittest.TestCase):
    @staticmethod
    def _media_routes(*, audio=(), image=(), video=()) -> MediaBackends:
        return MediaBackends(
            primary_inputs=frozenset({"text"}),
            audio=MediaRoute(True, 1024 * 1024, 2000, "转写音频", tuple(audio)),
            image=MediaRoute(True, 1024 * 1024, 1000, "描述图片", tuple(image)),
            video=MediaRoute(True, 1024 * 1024, 1000, "描述视频", tuple(video)),
        )

    def test_atomic_skill_runs_in_background_once(self) -> None:
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"move_relative",'
                '"arguments":{"distance_m":0.2},"reason":"前进"}'
            ]
        )
        robot = FakeRobotExecutor()
        dialogue, tasks = make_stack(model, robot)
        self.addCleanup(tasks.stop)

        state = invoke(dialogue, make_request("前进二十厘米"))
        snapshot = tasks.wait(state["task"]["task_id"])

        self.assertEqual(state["answer"], "已开始执行 move_relative。")
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual([call[0] for call in robot.calls], ["move_relative"])

    def test_reactive_skill_uses_new_camera_observation(self) -> None:
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"find_object",'
                '"arguments":{"target_name":"水瓶"},"reason":"开始搜索"}',
                '{"type":"skill_call","skill_name":"capture_camera",'
                '"arguments":{},"reason":"观察"}',
                '{"type":"final","status":"completed",'
                '"answer":"已经找到水瓶。","reason":"画面确认"}',
            ]
        )
        robot = FakeRobotExecutor()
        dialogue, tasks = make_stack(model, robot)
        self.addCleanup(tasks.stop)

        state = invoke(dialogue, make_request("找到水瓶"))
        snapshot = tasks.wait(state["task"]["task_id"])

        self.assertEqual(snapshot.answer, "已经找到水瓶。")
        self.assertEqual(robot.calls[0][0], "capture_camera")
        self.assertEqual(len(model.requests[-1].image_data_urls), 1)

    def test_reactive_skill_rejects_tool_outside_allowlist(self) -> None:
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"find_object",'
                '"arguments":{"target_name":"水瓶"},"reason":"开始"}',
                '{"type":"skill_call","skill_name":"get_robot_status",'
                '"arguments":{},"reason":"越权"}',
            ]
        )
        dialogue, tasks = make_stack(model, FakeRobotExecutor())
        self.addCleanup(tasks.stop)
        state = invoke(dialogue, make_request("找到水瓶"))

        snapshot = tasks.wait(state["task"]["task_id"])

        self.assertEqual(snapshot.status, "failed")
        self.assertIn("未获当前任务授权", snapshot.error)

    def test_dialogue_remains_available_while_skill_is_running(self) -> None:
        release = Event()
        robot = FakeRobotExecutor(blocker=release)
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"move_relative",'
                '"arguments":{"distance_m":0.3},"reason":"执行"}',
                '{"type":"final","status":"completed",'
                '"answer":"我还在执行任务。","reason":"普通对话"}',
            ]
        )
        dialogue, tasks = make_stack(model, robot)
        self.addCleanup(tasks.stop)
        first = invoke(dialogue, make_request("前进", "request-1"))
        self.assertTrue(robot.started.wait(1))

        second = invoke(dialogue, make_request("你还在吗", "request-2"))
        release.set()
        tasks.wait(first["task"]["task_id"])

        self.assertEqual(second["answer"], "我还在执行任务。")

    def test_new_skill_preempts_old_skill(self) -> None:
        release = Event()
        robot = FakeRobotExecutor(blocker=release)
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"move_relative",'
                '"arguments":{"distance_m":0.3},"reason":"旧任务"}',
                '{"type":"skill_call","skill_name":"rotate_relative",'
                '"arguments":{"angle_deg":30,"direction":"left"},'
                '"reason":"新任务"}',
            ]
        )
        dialogue, tasks = make_stack(model, robot)
        self.addCleanup(tasks.stop)
        first = invoke(dialogue, make_request("前进", "request-1"))
        self.assertTrue(robot.started.wait(1))

        second = invoke(dialogue, make_request("改成左转", "request-2"))
        release.set()
        old = tasks.wait(first["task"]["task_id"])
        new = tasks.wait(second["task"]["task_id"])

        self.assertEqual(old.status, "preempted")
        self.assertEqual(new.status, "completed")

    def test_explicit_task_control_cancels_running_skill(self) -> None:
        release = Event()
        robot = FakeRobotExecutor(blocker=release)
        model = FakeModel(
            [
                '{"type":"skill_call","skill_name":"move_relative",'
                '"arguments":{"distance_m":0.3},"reason":"执行"}',
                '{"type":"task_control","task_action":"cancel",'
                '"reason":"用户要求停止"}',
            ]
        )
        dialogue, tasks = make_stack(model, robot)
        self.addCleanup(tasks.stop)
        first = invoke(dialogue, make_request("前进", "request-1"))
        self.assertTrue(robot.started.wait(1))

        response = invoke(dialogue, make_request("不要继续了", "request-2"))
        release.set()
        snapshot = tasks.wait(first["task"]["task_id"])

        self.assertEqual(response["answer"], "已取消当前任务。")
        self.assertEqual(snapshot.status, "cancelled")

    def test_audio_falls_back_to_asr(self) -> None:
        model = FakeModel(
            ['{"type":"final","status":"completed","answer":"收到。","reason":"完成"}']
        )
        dialogue, tasks = make_stack(
            model,
            FakeRobotExecutor(),
            media=self._media_routes(audio=(FakeAsr(),)),
        )
        self.addCleanup(tasks.stop)
        request = RuntimeRequest(
            request_id="audio-test",
            source="test",
            inputs=[ContentPart(type=ContentType.AUDIO, data=b"RIFF-audio")],
        )

        state = invoke(dialogue, request)

        self.assertEqual(state["asr_backend"], "fake-asr")
        self.assertIn("向前走", model.requests[0].user_prompt)

    def test_speech_policy_still_applies_to_dialogue(self) -> None:
        model = FakeModel(
            ['{"type":"final","status":"completed","answer":"一二三四五六","reason":"完成"}']
        )
        speech = FakeSpeech(auto="always", max_chars=4)
        output = FakeAudioOutput()
        dialogue, tasks = make_stack(
            model,
            FakeRobotExecutor(),
            speech=speech,
            audio_output=output,
        )
        self.addCleanup(tasks.stop)

        invoke(dialogue, make_request("请回答"))

        self.assertEqual(speech.requests[0].text, "一二三四")
        self.assertEqual(output.calls[0]["audio"], b"RIFF-test")


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
