from __future__ import annotations

import unittest
from threading import Event

from llm_agent.runtime import (
    AgentRuntime,
    ContentPart,
    ContentType,
    InMemoryConversationStore,
    RuntimeRequest,
)


class RecordingGraph:
    def __init__(self) -> None:
        self.inputs = []

    def invoke(self, input: dict) -> dict:
        self.inputs.append(input)
        return {
            **input,
            "answer": "好的",
            "generation_backend": "fake-model",
            "speech_backend": "fake-tts",
            "command": {
                "schema": "small_car.motion.v1",
                "action": "move_relative",
                "distance_m": 1.0,
            },
        }


def make_request(
    *, audio_output: bool = False, session_id: str = "", text: str = "你好"
) -> RuntimeRequest:
    modalities = [ContentType.TEXT]
    if audio_output:
        modalities.append(ContentType.AUDIO)
    return RuntimeRequest(
        source="test",
        session_id=session_id,
        inputs=[ContentPart(type=ContentType.TEXT, text=text)],
        response_modalities=modalities,
    )


class RuntimeTest(unittest.TestCase):
    def test_runtime_returns_unified_multimodal_response(self) -> None:
        graph = RecordingGraph()
        request = make_request(audio_output=True)
        response = AgentRuntime(graph).run(request)
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.request_id, request.request_id)
        self.assertEqual(
            [part.type for part in response.outputs],
            [ContentType.TEXT, ContentType.JSON],
        )
        self.assertEqual(response.outputs[1].name, "robot_task")
        self.assertIn('"distance_m":1.0', response.outputs[1].text)
        self.assertIs(graph.inputs[0]["request"], request)

    def test_runtime_honours_request_cancellation(self) -> None:
        cancelled = Event()
        cancelled.set()
        response = AgentRuntime(RecordingGraph()).run(
            make_request(), cancel_token=cancelled
        )
        self.assertEqual(response.status, "cancelled")
        self.assertEqual(response.error_code, "cancelled")

    def test_runtime_rejects_new_request_after_stop(self) -> None:
        runtime = AgentRuntime(RecordingGraph())
        runtime.stop()
        response = runtime.run(make_request())
        self.assertEqual(response.status, "failed")
        self.assertEqual(response.error_code, "stopping")

    def test_runtime_passes_and_persists_session_history(self) -> None:
        graph = RecordingGraph()
        store = InMemoryConversationStore()
        runtime = AgentRuntime(graph, conversation_store=store)

        runtime.run(make_request(session_id="same", text="第一问"))
        second = runtime.run(make_request(session_id="same", text="第二问"))

        self.assertEqual(graph.inputs[0]["conversation_history"], [])
        history = graph.inputs[1]["conversation_history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].user_text, "第一问")
        self.assertEqual(history[0].assistant_text, "好的")
        self.assertEqual(second.metadata["conversation_history_turns"], 1)

    def test_runtime_does_not_mix_sessions(self) -> None:
        graph = RecordingGraph()
        runtime = AgentRuntime(
            graph, conversation_store=InMemoryConversationStore()
        )
        runtime.run(make_request(session_id="web", text="网页问题"))
        runtime.run(make_request(session_id="pi", text="小车问题"))
        self.assertEqual(graph.inputs[1]["conversation_history"], [])

    def test_runtime_can_clear_one_conversation(self) -> None:
        graph = RecordingGraph()
        runtime = AgentRuntime(
            graph, conversation_store=InMemoryConversationStore()
        )
        runtime.run(make_request(session_id="session", text="第一问"))
        runtime.clear_conversation("session")
        runtime.run(make_request(session_id="session", text="重新开始"))
        self.assertEqual(graph.inputs[1]["conversation_history"], [])


if __name__ == "__main__":
    unittest.main()
