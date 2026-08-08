from __future__ import annotations

import unittest

from llm_agent.agent.events import SpeechFinished, TextReceived, event_from_legacy
from llm_agent.agent.runtime import AgentRuntime


class RecordingGraph:
    def __init__(self) -> None:
        self.inputs = []

    def invoke(self, input: dict) -> dict:
        self.inputs.append(input)
        return {**input, "answer": "ok"}


class AgentEventsTest(unittest.TestCase):
    def test_converts_legacy_speech_event(self) -> None:
        event = event_from_legacy(
            {
                "event": "speech_finished",
                "speech_wav": b"wav",
                "perception": {},
            }
        )
        self.assertIsInstance(event, SpeechFinished)
        self.assertTrue(event.request_id)

    def test_runtime_passes_typed_event_and_request_id(self) -> None:
        graph = RecordingGraph()
        event = TextReceived(text="你好")
        result = AgentRuntime(graph).handle(event)
        self.assertEqual(result["request_id"], event.request_id)
        self.assertIs(graph.inputs[0]["event"], event)

    def test_runtime_rejects_new_turn_after_cancel(self) -> None:
        runtime = AgentRuntime(RecordingGraph())
        runtime.cancel()
        result = runtime.handle(TextReceived(text="你好"))
        self.assertIn("stopping", result["error"])


if __name__ == "__main__":
    unittest.main()
