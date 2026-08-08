from __future__ import annotations

import unittest

from llm_agent.agent.events import TextReceived
from llm_agent.agent.graph import build_graph
from llm_agent.models.types import ModelResponse, SpeechResponse
from llm_agent.tools.registry import ToolRegistry
from llm_agent.tools.vehicle.status import RobotStatus


class FakeModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.requests = []

    def complete(self, request) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(text=next(self.responses))


class FakeTts:
    def __init__(self) -> None:
        self.texts = []

    provider_name = "fake"

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
            available=True,
            motion_state="idle",
            battery_percentage=75.0,
        )


class AgentGraphTest(unittest.TestCase):
    def test_chat_skips_tools(self) -> None:
        model = FakeModel(
            [
                '{"intent":"chat","tool_name":null,"arguments":{},"reason":"问候"}',
                "你好，很高兴见到你。",
            ]
        )
        tts = FakeTts()
        graph = build_graph(model=model, tts=tts)
        event = TextReceived(text="你好")
        result = graph.invoke({"request_id": event.request_id, "event": event})
        self.assertEqual(result["answer"], "你好，很高兴见到你。")
        self.assertEqual(result["answer_wav"], b"RIFF-fake")
        self.assertEqual(len(model.requests), 2)

    def test_status_query_executes_tool_once(self) -> None:
        model = FakeModel(
            [
                '{"intent":"query","tool_name":"get_robot_status",'
                '"arguments":{},"reason":"查询电量"}',
                "小车当前空闲，电量百分之七十五。",
            ]
        )
        provider = FakeStatusProvider()
        graph = build_graph(model=model, tts=FakeTts(), status_provider=provider)
        event = TextReceived(text="小车还有多少电")
        result = graph.invoke({"request_id": event.request_id, "event": event})
        self.assertEqual(provider.calls, 1)
        self.assertTrue(result["tool_result"].success)
        self.assertEqual(result["tool_result"].data["battery_percentage"], 75.0)

    def test_action_is_not_executed(self) -> None:
        model = FakeModel(
            [
                '{"intent":"action","tool_name":null,"arguments":{},'
                '"reason":"要求前进"}'
            ]
        )
        result = build_graph(model=model, tts=FakeTts()).invoke(
            {
                "request_id": "action-request",
                "event": TextReceived(request_id="action-request", text="向前走"),
            }
        )
        self.assertIn("尚未开放", result["answer"])
        self.assertEqual(len(model.requests), 1)

    def test_unregistered_query_tool_is_rejected(self) -> None:
        model = FakeModel(
            [
                '{"intent":"query","tool_name":"publish_any_topic",'
                '"arguments":{},"reason":"非法工具"}',
                "这个工具不在允许列表中。",
            ]
        )
        result = build_graph(
            model=model, tts=FakeTts(), registry=ToolRegistry()
        ).invoke(
            {
                "request_id": "unsafe-request",
                "event": TextReceived(
                    request_id="unsafe-request", text="调用任意话题"
                ),
            }
        )
        self.assertIn("不在允许列表", result["answer"])
        self.assertIn("白名单", result["error"])


if __name__ == "__main__":
    unittest.main()
