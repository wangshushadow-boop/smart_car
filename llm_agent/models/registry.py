"""Provider 注册表与按配置选择后端的逻辑。

`ProviderRegistry` 是 Provider 工厂的字典视图；`select_backends` 把
`AgentConfig` 翻译成实际可用的 `GenerationBackend` / `SpeechBackend`。

`auto` 模式下：优先尝试 `preferred`，失败时回退到 `fallback`；两者通过
`FallbackSpeech` 包装，保证整轮请求不会因为 TTS 失败而中断。
"""

from __future__ import annotations

from collections.abc import Callable

from llm_agent.adapters.audio.tts import FallbackSpeech, PiperSpeech

from .minicpm import MiniCpmGeneration
from .minimax import MiniMaxGeneration, MiniMaxSpeech
from .protocol import GenerationBackend, SpeechBackend

GenerationFactory = Callable[[dict], GenerationBackend]
SpeechFactory = Callable[[dict], SpeechBackend]


class ProviderRegistry:
    """Provider 工厂注册表。"""

    def __init__(self) -> None:
        self._generation: dict[str, GenerationFactory] = {}
        self._speech: dict[str, SpeechFactory] = {}

    def register_generation(self, name: str, factory: GenerationFactory) -> None:
        """注册推理 Provider 工厂；同名重复注册抛错。"""
        if name in self._generation:
            raise ValueError(f"generation provider already registered: {name}")
        self._generation[name] = factory

    def register_speech(self, name: str, factory: SpeechFactory) -> None:
        """注册语音 Provider 工厂。"""
        if name in self._speech:
            raise ValueError(f"speech provider already registered: {name}")
        self._speech[name] = factory

    def has_speech(self, name: str) -> bool:
        """判断某语音 Provider 是否已注册（用于 auto 模式路由）。"""
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
    """构造内置默认 Provider 注册表。"""
    registry = ProviderRegistry()
    registry.register_generation("minicpm", MiniCpmGeneration)
    registry.register_generation("minimax", MiniMaxGeneration)
    registry.register_speech("minimax", MiniMaxSpeech)
    registry.register_speech("piper", PiperSpeech)
    return registry


def select_backends(config, registry: ProviderRegistry | None = None):
    """按 `AgentConfig` 选择推理与语音后端。

    返回 `(generation, speech)`。`auto` 模式下会用 `FallbackSpeech` 包装
    preferred 与 fallback；缺密钥或加载失败时静默回退。
    """
    registry = registry or create_default_registry()
    generation_name = config.generation.provider
    generation = registry.create_generation(
        generation_name, config.providers.get(generation_name, {})
    )

    selection = config.speech.provider
    if selection in {"native", "same_provider"}:
        # native / same_provider 表示"复用推理 Provider 自己的语音能力"。
        selection = generation_name
    if selection != "auto":
        # 显式 Provider：不静默回退，配置错误直接报错。
        speech = registry.create_speech(
            selection, config.providers.get(selection, {})
        )
        return generation, speech

    # auto 模式：先按 preferred 试，失败或不可用时回退到 fallback。
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
