from __future__ import annotations

import unittest
from types import SimpleNamespace

from llm_agent.asr import Qwen3Asr, TranscriptionRequest


class FakeQwenModel:
    def __init__(self) -> None:
        self.calls = []

    def transcribe(self, **kwargs):
        self.calls.append(kwargs)
        return [SimpleNamespace(text="向左转九十度", language="Chinese")]


class Qwen3AsrTest(unittest.TestCase):
    def test_model_is_loaded_only_on_first_transcription(self) -> None:
        qwen = FakeQwenModel()
        loads = []
        asr = Qwen3Asr(model_loader=lambda: loads.append(True) or qwen)

        self.assertFalse(asr.loaded)
        response = asr.transcribe(
            TranscriptionRequest(
                audio_data_urls=["data:audio/wav;base64,UklGRg=="]
            )
        )
        asr.transcribe(
            TranscriptionRequest(
                audio_data_urls=["data:audio/wav;base64,UklGRg=="]
            )
        )

        self.assertTrue(asr.loaded)
        self.assertEqual(len(loads), 1)
        self.assertEqual(response.text, "向左转九十度")
        self.assertEqual(response.language, "Chinese")
        self.assertEqual(
            qwen.calls[0]["audio"], ["data:audio/wav;base64,UklGRg=="]
        )
        self.assertEqual(qwen.calls[0]["language"], ["Chinese"])

    def test_empty_transcription_is_rejected(self) -> None:
        model = SimpleNamespace(
            transcribe=lambda **kwargs: [SimpleNamespace(text="", language="")]
        )
        asr = Qwen3Asr(model_loader=lambda: model)
        with self.assertRaisesRegex(RuntimeError, "empty"):
            asr.transcribe(TranscriptionRequest(audio_data_urls=["https://audio"]))


if __name__ == "__main__":
    unittest.main()
