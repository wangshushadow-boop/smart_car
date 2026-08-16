from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_agent.config import load_agent_config
from llm_agent.models.registry import (
    ProviderRegistry,
    check_required_model_services,
    create_default_registry,
    required_local_models,
    select_backends,
)
from llm_agent.models.protocol import ModelResponse, SpeechResponse


class FakeGeneration:
    provider_name = "fake_generation"

    def complete(self, request):
        return ModelResponse(text="ok", provider=self.provider_name)


class FakeSpeech:
    def __init__(self, name: str, fail: bool = False) -> None:
        self.provider_name = name
        self.fail = fail

    def synthesize(self, request):
        if self.fail:
            raise RuntimeError("failed")
        return SpeechResponse(
            audio_wav=b"wav",
            provider=self.provider_name,
            sample_rate=16_000,
            channels=1,
        )


class ProviderConfigTest(unittest.TestCase):
    def _config(self, content: str, models: str | None = None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "agent.yaml"
        if "\nmodalities:" not in content:
            content += """
modalities:
  input:
    audio: {enabled: false, models: []}
    image: {enabled: false, models: []}
    video: {enabled: false, models: []}
  output:
    audio: {enabled: false, models: []}
"""
        path.write_text(content, encoding="utf-8")
        models_path = Path(temporary.name) / "models.yaml"
        models_path.write_text(
            models
            or """
models:
  minicpm: {backend: minicpm, roles: [generation_model], input: [text, image, audio, video]}
  minimax: {backend: minimax, roles: [generation_model, speech], input: [text, image]}
  qwen3_asr: {backend: qwen3_asr, roles: [asr], input: [audio]}
  piper: {backend: piper, roles: [speech]}
  local: {backend: local, roles: [generation_model, speech]}
  cloud: {backend: cloud, roles: [speech]}
""",
            encoding="utf-8",
        )
        return load_agent_config(path, models_path)

    def test_environment_overrides_provider_selection(self) -> None:
        config_text = """
generation_model: minicpm
"""
        with patch.dict(
            "os.environ",
            {
                "CAR_GENERATION_MODEL": "minimax",
                "CAR_SPEECH_MODELS": "minimax,piper",
            },
        ):
            config = self._config(config_text)
        self.assertEqual(config.generation_model, "minimax")
        self.assertEqual(config.modalities.output.audio.models, ["minimax", "piper"])
        self.assertFalse(config.modalities.input.audio.enabled)
        self.assertTrue(config.runtime.conversation_enabled)
        self.assertEqual(config.runtime.conversation_max_turns, 8)

    def test_repository_config_declares_model_inputs_and_media_fallbacks(self) -> None:
        config = load_agent_config()
        self.assertEqual(config.generation_model, "minimax")
        self.assertEqual(config.models["minimax"].input, ["text", "image"])
        self.assertEqual(config.modalities.input.audio.models, ["qwen3_asr"])
        self.assertEqual(config.modalities.input.video.models, ["minicpm"])
        self.assertEqual(
            required_local_models(config),
            ["qwen3_asr", "minicpm", "piper"],
        )

    def test_models_are_loaded_from_separate_catalog(self) -> None:
        config = self._config(
            """
generation_model: local
""",
            """
models:
  local:
    backend: local
    roles: [generation_model]
    input: [text]
    model: local-model
    timeout_seconds: 12
  piper: {backend: piper, roles: [speech]}
""",
        )

        self.assertEqual(config.models["local"].backend, "local")
        self.assertEqual(config.models["local"].settings()["model"], "local-model")
        self.assertEqual(config.models["local"].settings()["input"], ["text"])
        self.assertNotIn("roles", config.models["local"].settings())

    def test_default_registry_does_not_expose_unsafe_minicpm_speech(self) -> None:
        registry = create_default_registry()
        self.assertFalse(registry.has_speech("minicpm"))

    def test_legacy_media_and_speech_sections_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._config(
                """
generation_model: local
media: {}
speech: {provider: piper}
"""
            )

    def test_duplicate_speech_models_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能包含重复模型"):
            self._config(
                """
generation_model: local
modalities:
  input:
    audio: {enabled: false, models: []}
    image: {enabled: false, models: []}
    video: {enabled: false, models: []}
  output:
    audio: {enabled: true, models: [piper, piper]}
"""
            )

    def test_required_local_models_follow_agent_capabilities(self) -> None:
        config = self._config(
            """
generation_model: minimax
modalities:
  input:
    audio: {enabled: true, models: [qwen3_asr]}
    image: {enabled: true, models: [minicpm]}
    video: {enabled: false, models: []}
  output:
    audio: {enabled: true, models: [minimax, piper]}
""",
            """
models:
  minimax:
    backend: minimax
    roles: [generation_model, speech]
    input: [text, image]
    deployment: {local: false}
  qwen3_asr:
    backend: qwen3_asr
    roles: [asr]
    input: [audio]
    deployment: {local: true, health_url: http://127.0.0.1:8100/health}
  piper:
    backend: piper
    roles: [speech]
    deployment: {local: true, health_url: http://127.0.0.1:8101/health}
""",
        )
        self.assertEqual(required_local_models(config), ["qwen3_asr", "piper"])

    def test_missing_model_services_report_start_command(self) -> None:
        config = self._config(
            """
generation_model: local
modalities:
  input:
    audio: {enabled: false, models: []}
    image: {enabled: false, models: []}
    video: {enabled: false, models: []}
  output:
    audio: {enabled: true, models: [piper]}
""",
            """
models:
  local:
    backend: local
    roles: [generation_model]
    input: [text, audio]
    deployment: {local: true, health_url: http://127.0.0.1:9000/health}
  piper:
    backend: piper
    roles: [speech]
    deployment: {local: true, health_url: http://127.0.0.1:8101/health}
""",
        )

        with self.assertRaisesRegex(
            RuntimeError, "start_models.sh local piper"
        ):
            check_required_model_services(
                config, opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline"))
            )

    def test_speech_models_are_tried_in_order(self) -> None:
        config = self._config(
            """
generation_model: local
modalities:
  input:
    audio: {enabled: false, models: []}
    image: {enabled: false, models: []}
    video: {enabled: false, models: []}
  output:
    audio: {enabled: true, models: [local, piper]}
"""
        )
        registry = ProviderRegistry()
        registry.register_generation("local", lambda settings: FakeGeneration())
        registry.register_speech(
            "local", lambda settings: FakeSpeech("local", fail=True)
        )
        registry.register_speech("piper", lambda settings: FakeSpeech("piper"))
        generation, _, speech = select_backends(config, registry)
        response = speech.synthesize(type("Request", (), {"text": "hello"})())
        self.assertEqual(generation.provider_name, "fake_generation")
        self.assertEqual(response.provider, "piper")

    def test_single_speech_model_propagates_failure(self) -> None:
        config = self._config(
            """
generation_model: local
modalities:
  input:
    audio: {enabled: false, models: []}
    image: {enabled: false, models: []}
    video: {enabled: false, models: []}
  output:
    audio: {enabled: true, models: [local]}
"""
        )
        registry = ProviderRegistry()
        registry.register_generation("local", lambda settings: FakeGeneration())
        registry.register_speech(
            "local", lambda settings: FakeSpeech("local", fail=True)
        )
        registry.register_speech("piper", lambda settings: FakeSpeech("piper"))
        _, _, speech = select_backends(config, registry)
        with self.assertRaises(RuntimeError):
            speech.synthesize(type("Request", (), {"text": "hello"})())

    def test_route_skips_model_that_cannot_be_created(self) -> None:
        config = self._config(
            """
generation_model: local
modalities:
  input:
    audio: {enabled: false, models: []}
    image: {enabled: false, models: []}
    video: {enabled: false, models: []}
  output:
    audio: {enabled: true, models: [cloud, piper]}
"""
        )
        registry = ProviderRegistry()
        registry.register_generation("local", lambda settings: FakeGeneration())
        registry.register_speech(
            "cloud", lambda settings: (_ for _ in ()).throw(RuntimeError("no key"))
        )
        registry.register_speech("piper", lambda settings: FakeSpeech("piper"))
        _, _, speech = select_backends(config, registry)
        self.assertEqual(speech.provider_name, "piper")

    def test_speech_route_does_not_depend_on_generation_backend(self) -> None:
        config = self._config(
            """
generation_model: local
modalities:
  input:
    audio: {enabled: false, models: []}
    image: {enabled: false, models: []}
    video: {enabled: false, models: []}
  output:
    audio: {enabled: true, models: [piper]}
"""
        )
        registry = ProviderRegistry()
        registry.register_generation("local", lambda settings: FakeGeneration())
        registry.register_speech("piper", lambda settings: FakeSpeech("piper"))
        _, _, speech = select_backends(config, registry)
        self.assertEqual(speech.provider_name, "piper")


if __name__ == "__main__":
    unittest.main()
