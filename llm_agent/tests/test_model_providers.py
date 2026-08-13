from __future__ import annotations

import io
import json
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import patch

from llm_agent.models.minimax.generation import MiniMaxGeneration
from llm_agent.models.minimax.speech import MiniMaxSpeech
from llm_agent.models.minicpm.generation import MiniCpmGeneration
from llm_agent.models.audio import inspect_pcm16_wav
from llm_agent.models.types import ModelRequest, SpeechRequest


def make_wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 160)
    return output.getvalue()


class FakeCompletions:
    def __init__(self) -> None:
        self.arguments = None

    def create(self, **kwargs):
        self.arguments = kwargs
        message = SimpleNamespace(content="云端回答")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeOpenAiClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions())


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class ModelProvidersTest(unittest.TestCase):
    def test_shared_audio_validator_accepts_pcm16_wav(self) -> None:
        self.assertEqual(inspect_pcm16_wav(make_wav()), (16_000, 1))

    def test_minicpm_maps_all_input_modalities(self) -> None:
        client = FakeOpenAiClient()
        model = MiniCpmGeneration(client=client)
        self.assertEqual(model.capabilities.intent_max_tokens, 160)
        self.assertEqual(model.capabilities.response_max_tokens, 256)
        model.complete(
            ModelRequest(
                system_prompt="system",
                user_prompt="hello",
                audio_data_urls=["data:audio/wav;base64,d2F2"],
                image_data_urls=["data:image/jpeg;base64,anBn"],
                video_data_urls=["data:video/mp4;base64,bXA0"],
            )
        )
        content = client.chat.completions.arguments["messages"][1]["content"]
        self.assertEqual(
            [part["type"] for part in content],
            ["text", "image_url", "audio_url", "video_url"],
        )

    def test_minimax_generation_uses_provider_specific_parameters(self) -> None:
        client = FakeOpenAiClient()
        model = MiniMaxGeneration({"model": "MiniMax-M3"}, client=client)
        self.assertEqual(model.capabilities.intent_max_tokens, 2048)
        self.assertEqual(model.capabilities.response_max_tokens, 2048)
        response = model.complete(
            ModelRequest(
                system_prompt="system",
                user_prompt="hello",
                temperature=0,
            )
        )
        self.assertEqual(response.provider, "minimax")
        self.assertEqual(response.text, "云端回答")
        self.assertEqual(client.chat.completions.arguments["temperature"], 0.01)
        self.assertIn("reasoning_split", client.chat.completions.arguments["extra_body"])

    def test_generation_parameters_can_be_overridden_per_provider(self) -> None:
        minicpm = MiniCpmGeneration(
            {
                "intent_max_tokens": 320,
                "intent_temperature": 0.1,
                "response_max_tokens": 640,
                "response_temperature": 0.4,
            },
            client=FakeOpenAiClient(),
        )
        minimax_client = FakeOpenAiClient()
        minimax = MiniMaxGeneration(
            {
                "intent_max_tokens": 1024,
                "intent_temperature": 0.02,
                "response_max_tokens": 1536,
                "response_temperature": 0.3,
                "reasoning_split": False,
            },
            client=minimax_client,
        )

        self.assertEqual(minicpm.capabilities.intent_max_tokens, 320)
        self.assertEqual(minicpm.capabilities.response_temperature, 0.4)
        self.assertEqual(minimax.capabilities.intent_temperature, 0.02)
        self.assertEqual(minimax.capabilities.response_max_tokens, 1536)
        minimax.complete(ModelRequest(system_prompt="system", user_prompt="hello"))
        self.assertFalse(
            minimax_client.chat.completions.arguments["extra_body"]["reasoning_split"]
        )

    def test_minimax_openai_ignores_claude_code_model_override(self) -> None:
        client = FakeOpenAiClient()
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_MODEL": '"MiniMax-M3[1m]'},
            clear=True,
        ):
            model = MiniMaxGeneration(
                {"protocol": "openai", "model": "MiniMax-M3"}, client=client
            )
            model.complete(ModelRequest(system_prompt="system", user_prompt="hello"))
        self.assertEqual(
            client.chat.completions.arguments["model"], "MiniMax-M3"
        )

    def test_minimax_generation_rejects_unsupported_audio(self) -> None:
        model = MiniMaxGeneration(client=FakeOpenAiClient())
        with self.assertRaisesRegex(ValueError, "audio"):
            model.complete(
                ModelRequest(
                    system_prompt="system",
                    user_prompt="hello",
                    audio_data_urls=["data:audio/wav;base64,d2F2"],
                )
            )

    def test_minimax_openai_maps_image_input(self) -> None:
        client = FakeOpenAiClient()
        model = MiniMaxGeneration(client=client)

        model.complete(
            ModelRequest(
                system_prompt="system",
                user_prompt="前方有什么？",
                image_data_urls=["data:image/jpeg;base64,anBn"],
            )
        )

        content = client.chat.completions.arguments["messages"][1]["content"]
        self.assertTrue(model.capabilities.image_input)
        self.assertEqual([item["type"] for item in content], ["text", "image_url"])
        self.assertEqual(
            content[1]["image_url"]["url"], "data:image/jpeg;base64,anBn"
        )

    def test_minimax_generation_supports_anthropic_environment(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeHttpResponse(
                {
                    "content": [
                        {"type": "thinking", "thinking": "internal"},
                        {"type": "text", "text": "云端回答"},
                    ]
                }
            )

        with patch.dict(
            "os.environ",
            {
                "ANTHROPIC_AUTH_TOKEN": "test-token",
                "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic/",
                "ANTHROPIC_MODEL": '"MiniMax-M3"',
            },
            clear=True,
        ):
            model = MiniMaxGeneration({"protocol": "anthropic"}, opener=opener)
            response = model.complete(
                ModelRequest(
                    system_prompt="system",
                    user_prompt="hello",
                    temperature=0,
                )
            )

        self.assertEqual(response.text, "云端回答")
        self.assertEqual(captured["timeout"], 90)
        self.assertEqual(captured["request"].full_url, "https://api.minimaxi.com/anthropic/v1/messages")
        self.assertEqual(captured["request"].get_header("X-api-key"), "test-token")
        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(payload["model"], "MiniMax-M3")
        self.assertEqual(payload["temperature"], 0.01)

    def test_minimax_anthropic_maps_base64_image_input(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(
                {"content": [{"type": "text", "text": "看到小车。"}]}
            )

        with patch.dict(
            "os.environ",
            {
                "ANTHROPIC_AUTH_TOKEN": "test-token",
                "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
            },
            clear=True,
        ):
            model = MiniMaxGeneration({"protocol": "anthropic"}, opener=opener)
            model.complete(
                ModelRequest(
                    system_prompt="system",
                    user_prompt="描述图片",
                    image_data_urls=["data:image/jpeg;base64,anBn"],
                )
            )

        content = captured["payload"]["messages"][0]["content"]
        self.assertEqual(content[1]["type"], "image")
        self.assertEqual(content[1]["source"]["media_type"], "image/jpeg")
        self.assertEqual(content[1]["source"]["data"], "anBn")

    def test_minimax_speech_decodes_and_validates_wav(self) -> None:
        wav = make_wav()
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeHttpResponse(
                {
                    "data": {"audio": wav.hex(), "status": 2},
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                }
            )

        speech = MiniMaxSpeech({"speech_timeout_seconds": 12}, opener=opener)
        response = speech.synthesize(SpeechRequest(text="你好"))
        self.assertEqual(response.provider, "minimax")
        self.assertEqual(response.audio_wav, wav)
        self.assertEqual(response.sample_rate, 16_000)
        self.assertEqual(captured["timeout"], 12)
        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(payload["audio_setting"]["format"], "wav")

    def test_minimax_speech_rejects_invalid_audio(self) -> None:
        def opener(request, timeout):
            return FakeHttpResponse(
                {
                    "data": {"audio": b"not-wav".hex()},
                    "base_resp": {"status_code": 0},
                }
            )

        with self.assertRaisesRegex(ValueError, "WAV"):
            MiniMaxSpeech(opener=opener).synthesize(SpeechRequest(text="你好"))


if __name__ == "__main__":
    unittest.main()
