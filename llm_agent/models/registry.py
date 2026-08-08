"""Provider registry and configuration-driven backend selection."""

from __future__ import annotations

from collections.abc import Callable

from llm_agent.adapters.audio.tts import FallbackSpeech, PiperSpeech

from .minicpm import MiniCpmGeneration, MiniCpmSpeech
from .minimax import MiniMaxGeneration, MiniMaxSpeech
from .protocol import GenerationBackend, SpeechBackend

GenerationFactory = Callable[[dict], GenerationBackend]
SpeechFactory = Callable[[dict], SpeechBackend]


class ProviderRegistry:
    def __init__(self) -> None:
        self._generation: dict[str, GenerationFactory] = {}
        self._speech: dict[str, SpeechFactory] = {}

    def register_generation(self, name: str, factory: GenerationFactory) -> None:
        if name in self._generation:
            raise ValueError(f"generation provider already registered: {name}")
        self._generation[name] = factory

    def register_speech(self, name: str, factory: SpeechFactory) -> None:
        if name in self._speech:
            raise ValueError(f"speech provider already registered: {name}")
        self._speech[name] = factory

    def has_speech(self, name: str) -> bool:
        return name in self._speech

    def create_generation(self, name: str, settings: dict) -> GenerationBackend:
        factory = self._generation.get(name)
        if factory is None:
            raise ValueError(f"unknown generation provider: {name}")
        return factory(settings)

    def create_speech(self, name: str, settings: dict) -> SpeechBackend:
        factory = self._speech.get(name)
        if factory is None:
            raise ValueError(f"unknown speech provider: {name}")
        return factory(settings)


def create_default_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register_generation("minicpm", MiniCpmGeneration)
    registry.register_generation("minimax", MiniMaxGeneration)
    registry.register_speech("minicpm", MiniCpmSpeech)
    registry.register_speech("minimax", MiniMaxSpeech)
    registry.register_speech("piper", PiperSpeech)
    return registry


def select_backends(config, registry: ProviderRegistry | None = None):
    registry = registry or create_default_registry()
    generation_name = config.generation.provider
    generation = registry.create_generation(
        generation_name, config.providers.get(generation_name, {})
    )

    selection = config.speech.provider
    if selection in {"native", "same_provider"}:
        selection = generation_name
    if selection != "auto":
        speech = registry.create_speech(
            selection, config.providers.get(selection, {})
        )
        return generation, speech

    preferred = config.speech.preferred
    if preferred in {"native", "same_provider"}:
        preferred = generation_name
    fallback_name = config.speech.fallback
    fallback = registry.create_speech(
        fallback_name, config.providers.get(fallback_name, {})
    )
    if not registry.has_speech(preferred) or preferred == fallback_name:
        return generation, fallback
    try:
        primary = registry.create_speech(
            preferred, config.providers.get(preferred, {})
        )
    except Exception:
        # Auto mode remains available when an optional cloud provider has no
        # key, or a local native-speech dependency is unavailable at startup.
        return generation, fallback
    return generation, FallbackSpeech(primary, fallback)
