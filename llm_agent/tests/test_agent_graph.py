from __future__ import annotations

import unittest
from threading import Event

from llm_agent.agent.graph import build_graph
from llm_agent.models.types import ModelResponse, SpeechResponse
from llm_agent.runtime import ContentPart, ContentType, RuntimeRequest
from llm_agent.tools.registry import ToolRegistry
from llm_agent.tools.vehicle.status import RobotStatus


class FakeModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.requests = []

    def complete(self, request) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(text=next(self.responses), provider="fake-model")


class FakeTts:
    provider_name = "fake-tts"

    def __init__(self) -> None:
        self.texts = []

    def synthesize(self, request) -> SpeechResponse:
        self.texts.append(request.text)
        return SpeechResponse(
            audio_wav=b"RIFF-fake",
            provider=self.provider_name,
            sample_rate=16_000,
            channels=1,
        )


class FakeStatusProvider:
    def __init__(self) -> None:
        self.calls = 0

    def get_status(self) -> RobotStatus:
        self.calls += 1
        return RobotStatus(
            available=True, motion_state="idle", battery_percentage=75.0
        )


def make_request(
    text: str, *, request_id: str = "test-request", audio_output: bool = True,
    allow_tools: bool = True
) -> RuntimeRequest:
    modalities = [ContentType.TEXT]
    if audio_output:
        modalities.append(ContentType.AUDIO)
    return RuntimeRequest(
        request_id=request_id,
        source="test",
        inputs=[ContentPart(type=ContentType.TEXT, text=text)],
        response_modalities=modalities,
        allow_tools=allow_tools,
    )


def invoke(graph, request: RuntimeRequest) -> dict:
    return graph.invoke(
        {
            "request_id": request.request_id,
            "request": request,
            "cancel_token": Event(),
        }
    )


class AgentGraphTest(unittest.TestCase):
    def test_chat_skips_tools(self) -> None:
        model = FakeModel([
            '{"intent":"chat","tool_name":null,"arguments":{},"reason":"问候"}',
            "你好，很高兴见到你。",
        ])
        result = invoke(build_graph(model=model, tts=FakeTts()), make_request("你好"))
        self.assertEqual(result["answer"], "你好，很高兴见到你。")
        self.assertEqual(result["answer_wav"], b"RIFF-fake")
        self.assertEqual(len(model.requests), 2)

    def test_request_can_disable_audio_output(self) -> None:
        model = FakeModel([
            '{"intent":"chat","tool_name":null,"arguments":{},"reason":"文本"}',
            "纯文本回答",
        ])
        tts = FakeTts()
        result = invoke(
            build_graph(model=model, tts=tts),
            make_request("只返回文字", audio_output=False),
        )
        self.assertNotIn("answer_wav", result)
        self.assertEqual(tts.texts, [])

    def test_status_query_executes_tool_once(self) -> None:
        model = FakeModel([
            '{"intent":"query","tool_name":"get_robot_status","arguments":{},"reason":"查询"}',
            "小车当前空闲，电量百分之七十五。",
        ])
        provider = FakeStatusProvider()
        result = invoke(
            build_graph(model=model, tts=FakeTts(), status_provider=provider),
            make_request("小车还有多少电"),
        )
        self.assertEqual(provider.calls, 1)
        self.assertTrue(result["tool_result"].success)

    def test_relative_motion_becomes_declarative_command(self) -> None:
        model = FakeModel([
            '{"intent":"action","tool_name":"move_relative",'
            '"arguments":{"distance_m":1.0},"reason":"要求前进一米"}'
        ])
        result = invoke(
            build_graph(model=model, tts=FakeTts()), make_request("向前一米")
        )
        self.assertEqual(result["command"]["action"], "move_relative")
        self.assertEqual(result["command"]["distance_m"], 1.0)
        self.assertIn("前进1米", result["answer"])
        self.assertEqual(len(model.requests), 1)

    def test_motion_outside_whitelist_is_rejected(self) -> None:
        model = FakeModel([
            '{"intent":"action","tool_name":"move_relative",'
            '"arguments":{"distance_m":10.0},"reason":"距离越界"}'
        ])
        result = invoke(
            build_graph(model=model, tts=FakeTts()), make_request("向前十米")
        )
        self.assertNotIn("command", result)
        self.assertIn("安全校验", result["answer"])
        self.assertFalse(result["tool_result"].success)

    def test_cancel_becomes_stop_command(self) -> None:
        model = FakeModel([
            '{"intent":"cancel","tool_name":"stop_motion",'
            '"arguments":{},"reason":"用户要求停止"}'
        ])
        result = invoke(
            build_graph(model=model, tts=FakeTts()), make_request("停止")
        )
        self.assertEqual(result["command"]["action"], "stop_motion")

    def test_request_can_disable_tools(self) -> None:
        model = FakeModel([
            '{"intent":"query","tool_name":"get_robot_status","arguments":{},"reason":"查询"}',
            "本轮禁止调用工具。",
        ])
        result = invoke(
            build_graph(model=model, tts=FakeTts()),
            make_request("查询状态", allow_tools=False),
        )
        self.assertIn("禁止调用工具", result["error"])

    def test_unregistered_query_tool_is_rejected(self) -> None:
        model = FakeModel([
            '{"intent":"query","tool_name":"publish_any_topic","arguments":{},"reason":"非法"}',
            "这个工具不在允许列表中。",
        ])
        result = invoke(
            build_graph(model=model, tts=FakeTts(), registry=ToolRegistry()),
            make_request("调用任意话题"),
        )
        self.assertIn("白名单", result["error"])


if __name__ == "__main__":
    unittest.main()
