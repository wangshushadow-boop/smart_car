from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_agent.app.config import load_agent_config
from llm_agent.models.registry import (
    ProviderRegistry,
    create_default_registry,
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
    def _config(self, content: str):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "agent.yaml"
        path.write_text(content, encoding="utf-8")
        return load_agent_config(path)

    def test_environment_overrides_provider_selection(self) -> None:
        config_text = """
generation:
  provider: minicpm
speech:
  provider: piper
  preferred: same_provider
  fallback: piper
providers: {}
"""
        with patch.dict(
            "os.environ",
            {
                "CAR_GENERATION_PROVIDER": "minimax",
                "CAR_SPEECH_PROVIDER": "auto",
            },
        ):
            config = self._config(config_text)
        self.assertEqual(config.generation.provider, "minimax")
        self.assertEqual(config.speech.provider, "auto")

    def test_default_registry_does_not_expose_unsafe_minicpm_speech(self) -> None:
        registry = create_default_registry()
        self.assertFalse(registry.has_speech("minicpm"))

    def test_auto_uses_same_provider_then_fallback(self) -> None:
        config = self._config(
            """
generation:
  provider: local
speech:
  provider: auto
  preferred: same_provider
  fallback: piper
providers:
  local: {}
  piper: {}
"""
        )
        registry = ProviderRegistry()
        registry.register_generation("local", lambda settings: FakeGeneration())
        registry.register_speech(
            "local", lambda settings: FakeSpeech("local", fail=True)
        )
        registry.register_speech("piper", lambda settings: FakeSpeech("piper"))
        generation, speech = select_backends(config, registry)
        response = speech.synthesize(type("Request", (), {"text": "hello"})())
        self.assertEqual(generation.provider_name, "fake_generation")
        self.assertEqual(response.provider, "piper")

    def test_explicit_speech_provider_does_not_fallback(self) -> None:
        config = self._config(
            """
generation:
  provider: local
speech:
  provider: local
  preferred: same_provider
  fallback: piper
providers:
  local: {}
  piper: {}
"""
        )
        registry = ProviderRegistry()
        registry.register_generation("local", lambda settings: FakeGeneration())
        registry.register_speech(
            "local", lambda settings: FakeSpeech("local", fail=True)
        )
        registry.register_speech("piper", lambda settings: FakeSpeech("piper"))
        _, speech = select_backends(config, registry)
        with self.assertRaises(RuntimeError):
            speech.synthesize(type("Request", (), {"text": "hello"})())

    def test_auto_falls_back_when_primary_cannot_be_created(self) -> None:
        config = self._config(
            """
generation:
  provider: local
speech:
  provider: auto
  preferred: cloud
  fallback: piper
providers: {}
"""
        )
        registry = ProviderRegistry()
        registry.register_generation("local", lambda settings: FakeGeneration())
        registry.register_speech(
            "cloud", lambda settings: (_ for _ in ()).throw(RuntimeError("no key"))
        )
        registry.register_speech("piper", lambda settings: FakeSpeech("piper"))
        _, speech = select_backends(config, registry)
        self.assertEqual(speech.provider_name, "piper")

    def test_auto_uses_fallback_when_generation_has_no_speech_backend(self) -> None:
        config = self._config(
            """
generation:
  provider: local
speech:
  provider: auto
  preferred: same_provider
  fallback: piper
providers: {}
"""
        )
        registry = ProviderRegistry()
        registry.register_generation("local", lambda settings: FakeGeneration())
        registry.register_speech("piper", lambda settings: FakeSpeech("piper"))
        _, speech = select_backends(config, registry)
        self.assertEqual(speech.provider_name, "piper")


if __name__ == "__main__":
    unittest.main()
