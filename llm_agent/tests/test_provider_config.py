from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_agent.app.config import load_agent_config
from llm_agent.models.registry import (
    ProviderRegistry,
    check_required_model_services,
    create_default_registry,
    required_local_models,
    select_backends,
)
from llm_agent.models.types import ModelResponse, SpeechResponse


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
        if "\nasr:" not in content:
            content += "\nasr:\n  provider: none\n  fallback: qwen3_asr\n"
        path.write_text(content, encoding="utf-8")
        models_path = Path(temporary.name) / "models.yaml"
        models_path.write_text(
            models
            or """
models:
  minicpm: {backend: minicpm, roles: [generation_model]}
  minimax: {backend: minimax, roles: [generation_model, speech]}
  qwen3_asr: {backend: qwen3_asr, roles: [asr]}
  piper: {backend: piper, roles: [speech]}
  local: {backend: local, roles: [generation_model, speech]}
  cloud: {backend: cloud, roles: [speech]}
""",
            encoding="utf-8",
        )
        return load_agent_config(path, models_path)

    def test_environment_overrides_provider_selection(self) -> None:
        config_text = """
generation_model:
  provider: minicpm
speech:
  provider: piper
  preferred: same_provider
  fallback: piper
"""
        with patch.dict(
            "os.environ",
            {
                "CAR_GENERATION_MODEL": "minimax",
                "CAR_SPEECH_PROVIDER": "auto",
                "CAR_ASR_PROVIDER": "none",
            },
        ):
            config = self._config(config_text)
        self.assertEqual(config.generation_model.provider, "minimax")
        self.assertEqual(config.speech.provider, "auto")
        self.assertEqual(config.asr.provider, "none")
        self.assertTrue(config.runtime.conversation_enabled)
        self.assertEqual(config.runtime.conversation_max_turns, 8)

    def test_models_are_loaded_from_separate_catalog(self) -> None:
        config = self._config(
            """
generation_model: {provider: local}
asr: {provider: none, fallback: qwen3_asr}
speech: {provider: piper, preferred: same_provider, fallback: piper}
""",
            """
models:
  local:
    backend: local
    roles: [generation_model]
    model: local-model
    timeout_seconds: 12
  piper: {backend: piper, roles: [speech]}
""",
        )

        self.assertEqual(config.models["local"].backend, "local")
        self.assertEqual(config.models["local"].settings()["model"], "local-model")
        self.assertNotIn("roles", config.models["local"].settings())

    def test_default_registry_does_not_expose_unsafe_minicpm_speech(self) -> None:
        registry = create_default_registry()
        self.assertFalse(registry.has_speech("minicpm"))

    def test_required_local_models_follow_agent_capabilities(self) -> None:
        config = self._config(
            """
generation_model: {provider: minimax}
asr: {provider: auto, fallback: qwen3_asr}
speech: {provider: auto, preferred: same_provider, fallback: piper}
""",
            """
models:
  minimax:
    backend: minimax
    roles: [generation_model, speech]
    capabilities: {audio_input: false}
    deployment: {local: false}
  qwen3_asr:
    backend: qwen3_asr
    roles: [asr]
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
generation_model: {provider: local}
asr: {provider: none, fallback: qwen3_asr}
speech: {provider: piper, preferred: same_provider, fallback: piper}
""",
            """
models:
  local:
    backend: local
    roles: [generation_model]
    capabilities: {audio_input: true}
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

    def test_auto_uses_same_provider_then_fallback(self) -> None:
        config = self._config(
            """
generation_model:
  provider: local
speech:
  provider: auto
  preferred: same_provider
  fallback: piper
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

    def test_explicit_speech_provider_does_not_fallback(self) -> None:
        config = self._config(
            """
generation_model:
  provider: local
speech:
  provider: local
  preferred: same_provider
  fallback: piper
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

    def test_auto_falls_back_when_primary_cannot_be_created(self) -> None:
        config = self._config(
            """
generation_model:
  provider: local
speech:
  provider: auto
  preferred: cloud
  fallback: piper
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

    def test_auto_uses_fallback_when_generation_has_no_speech_backend(self) -> None:
        config = self._config(
            """
generation_model:
  provider: local
speech:
  provider: auto
  preferred: same_provider
  fallback: piper
"""
        )
        registry = ProviderRegistry()
        registry.register_generation("local", lambda settings: FakeGeneration())
        registry.register_speech("piper", lambda settings: FakeSpeech("piper"))
        _, _, speech = select_backends(config, registry)
        self.assertEqual(speech.provider_name, "piper")


if __name__ == "__main__":
    unittest.main()
