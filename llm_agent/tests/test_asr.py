from __future__ import annotations

import json
import unittest

from llm_agent.models.qwen3_asr import Qwen3Asr, TranscriptionRequest


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class Qwen3AsrTest(unittest.TestCase):
    def test_transcribe_calls_external_service(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeHttpResponse(
                {
                    "text": "向左转九十度",
                    "provider": "qwen3_asr",
                    "language": "Chinese",
                }
            )

        asr = Qwen3Asr(
            {"endpoint": "http://127.0.0.1:8100", "timeout_seconds": 12},
            opener=opener,
        )
        response = asr.transcribe(
            TranscriptionRequest(
                audio_data_urls=["data:audio/wav;base64,UklGRg=="]
            )
        )

        self.assertEqual(response.text, "向左转九十度")
        self.assertEqual(response.language, "Chinese")
        self.assertEqual(captured["timeout"], 12)
        self.assertEqual(captured["request"].full_url, "http://127.0.0.1:8100/transcribe")
        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(payload["audio_data_urls"], ["data:audio/wav;base64,UklGRg=="])

    def test_service_error_is_rejected(self) -> None:
        asr = Qwen3Asr(opener=lambda *_args, **_kwargs: FakeHttpResponse({"error": "offline"}))
        with self.assertRaisesRegex(RuntimeError, "offline"):
            asr.transcribe(TranscriptionRequest(audio_data_urls=["https://audio"]))


if __name__ == "__main__":
    unittest.main()
