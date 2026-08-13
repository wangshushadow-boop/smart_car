"""Provider 注册表与按配置选择后端的逻辑。

`ProviderRegistry` 是 Provider 工厂的字典视图；`select_backends` 把
`AgentConfig` 翻译成实际可用的 `GenerationBackend` / `SpeechBackend`。

`auto` 模式下：优先尝试 `preferred`，失败时回退到 `fallback`；两者通过
`FallbackSpeech` 包装，保证整轮请求不会因为 TTS 失败而中断。
"""

from __future__ import annotations

from collections.abc import Callable

from .capabilities import SpeechCapabilities
from .minicpm import MiniCpmGeneration
from .minimax import MiniMaxGeneration, MiniMaxSpeech
from .piper import PiperSpeech
from .protocol import AsrBackend, GenerationBackend, SpeechBackend
from .qwen3_asr import Qwen3Asr
from .types import SpeechRequest, SpeechResponse

GenerationFactory = Callable[[dict], GenerationBackend]
SpeechFactory = Callable[[dict], SpeechBackend]
AsrFactory = Callable[[dict], AsrBackend]


class FallbackSpeech:
    """语音选择策略：主后端失败时调用配置的备后端。"""

    capabilities = SpeechCapabilities(
        wav_output=True, streaming=False, configurable_voice=True
    )

    def __init__(self, primary: SpeechBackend, fallback: SpeechBackend) -> None:
        self._primary = primary
        self._fallback = fallback
        self.provider_name = f"auto:{primary.provider_name}->{fallback.provider_name}"

    def synthesize(self, request: SpeechRequest) -> SpeechResponse:
        try:
            return self._primary.synthesize(request)
        except Exception:
            return self._fallback.synthesize(request)


class ProviderRegistry:
    """Provider 工厂注册表。"""

    def __init__(self) -> None:
        self._generation: dict[str, GenerationFactory] = {}
        self._speech: dict[str, SpeechFactory] = {}
        self._asr: dict[str, AsrFactory] = {}

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

    def register_asr(self, name: str, factory: AsrFactory) -> None:
        if name in self._asr:
            raise ValueError(f"ASR provider already registered: {name}")
        self._asr[name] = factory

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

    def create_asr(self, name: str, settings: dict) -> AsrBackend:
        factory = self._asr.get(name)
        if factory is None:
            raise ValueError(f"unknown ASR backend: {name}")
        return factory(settings)


def create_default_registry() -> ProviderRegistry:
    """构造内置默认 Provider 注册表。"""
    registry = ProviderRegistry()
    registry.register_generation("minicpm", MiniCpmGeneration)
    registry.register_generation("minimax", MiniMaxGeneration)
    registry.register_speech("minimax", MiniMaxSpeech)
    registry.register_speech("piper", PiperSpeech)
    registry.register_asr("qwen3_asr", Qwen3Asr)
    return registry


def _model(config, name: str, role: str):
    model = config.models.get(name)
    if model is None:
        raise ValueError(f"unknown {role} model: {name}")
    if role not in model.roles:
        raise ValueError(f"model {name} does not provide role: {role}")
    return model


def select_backends(config, registry: ProviderRegistry | None = None):
    """按 `AgentConfig` 选择推理与语音后端。

    返回 `(generation, asr, speech)`。ASR auto 按 generation 的音频能力
    决定是否启用；speech auto 用 `FallbackSpeech` 包装主备后端。
    """
    registry = registry or create_default_registry()
    generation_name = config.generation_model.provider
    generation_model = _model(config, generation_name, "generation_model")
    generation = registry.create_generation(
        generation_model.backend, generation_model.settings()
    )

    asr_selection = config.asr.provider
    if asr_selection == "auto":
        asr_selection = (
            "none" if generation.capabilities.audio_input else config.asr.fallback
        )
    if asr_selection == "none":
        asr = None
    else:
        asr_model = _model(config, asr_selection, "asr")
        asr = registry.create_asr(asr_model.backend, asr_model.settings())

    selection = config.speech.provider
    if selection in {"native", "same_provider"}:
        # native / same_provider 表示"复用推理 Provider 自己的语音能力"。
        selection = generation_name
    if selection != "auto":
        # 显式 Provider：不静默回退，配置错误直接报错。
        speech_model = _model(config, selection, "speech")
        speech = registry.create_speech(speech_model.backend, speech_model.settings())
        return generation, asr, speech

    # auto 模式：先按 preferred 试，失败或不可用时回退到 fallback。
    preferred = config.speech.preferred
    if preferred in {"native", "same_provider"}:
        preferred = generation_name
    fallback_name = config.speech.fallback
    fallback_model = _model(config, fallback_name, "speech")
    fallback = registry.create_speech(
        fallback_model.backend, fallback_model.settings()
    )
    preferred_model = config.models.get(preferred)
    if (
        preferred_model is None
        or "speech" not in preferred_model.roles
        or not registry.has_speech(preferred_model.backend)
        or preferred == fallback_name
    ):
        return generation, asr, fallback
    try:
        primary = registry.create_speech(
            preferred_model.backend, preferred_model.settings()
        )
    except Exception:
        # Auto mode remains available when an optional cloud provider has no
        # key, or a local native-speech dependency is unavailable at startup.
        return generation, asr, fallback
    return generation, asr, FallbackSpeech(primary, fallback)
