from __future__ import annotations

import unittest
from threading import Event

from llm_agent.runtime import AgentRuntime, ContentPart, ContentType, RuntimeRequest


class RecordingGraph:
    def __init__(self) -> None:
        self.inputs = []

    def invoke(self, input: dict) -> dict:
        self.inputs.append(input)
        return {
            **input,
            "answer": "好的",
            "answer_wav": b"RIFF-test",
            "generation_backend": "fake-model",
            "speech_backend": "fake-tts",
            "command": {
                "schema": "small_car.motion.v1",
                "action": "move_relative",
                "distance_m": 1.0,
            },
        }


def make_request(*, audio_output: bool = False) -> RuntimeRequest:
    modalities = [ContentType.TEXT]
    if audio_output:
        modalities.append(ContentType.AUDIO)
    return RuntimeRequest(
        source="test",
        inputs=[ContentPart(type=ContentType.TEXT, text="你好")],
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
            [ContentType.TEXT, ContentType.JSON, ContentType.AUDIO],
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


if __name__ == "__main__":
    unittest.main()
