"""Provider 注册表与按配置选择后端的逻辑。

`ProviderRegistry` 是 Provider 工厂的字典视图；`select_backends` 把
`AgentConfig` 翻译成实际可用的 `GenerationBackend` / `SpeechBackend`。

`auto` 模式下：优先尝试 `preferred`，失败时回退到 `fallback`；两者通过
`FallbackSpeech` 包装，保证整轮请求不会因为 TTS 失败而中断。
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.request import urlopen

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


def required_local_models(config) -> list[str]:
    """解析当前 Agent 配置实际依赖的本地模型服务。

    这里仅做配置计算，不创建 Provider。auto ASR 根据生成模型声明的
    ``capabilities.audio_input`` 决定；speech auto 始终检查本地 fallback，
    同时检查本地 preferred。返回结果去重且保持调用顺序。
    """
    required: list[str] = []

    def add_if_local(name: str) -> None:
        model = config.models.get(name)
        if model and model.settings().get("deployment", {}).get("local", False):
            if name not in required:
                required.append(name)

    generation_name = config.generation_model.provider
    generation_model = _model(config, generation_name, "generation_model")
    add_if_local(generation_name)

    asr_name = config.asr.provider
    if asr_name == "auto":
        capabilities = generation_model.settings().get("capabilities", {})
        asr_name = "none" if capabilities.get("audio_input", False) else config.asr.fallback
    if asr_name != "none":
        _model(config, asr_name, "asr")
        add_if_local(asr_name)

    speech_name = config.speech.provider
    if speech_name == "auto":
        preferred = config.speech.preferred
        if preferred in {"native", "same_provider"}:
            preferred = generation_name
        if preferred in config.models:
            add_if_local(preferred)
        _model(config, config.speech.fallback, "speech")
        add_if_local(config.speech.fallback)
    else:
        if speech_name in {"native", "same_provider"}:
            speech_name = generation_name
        _model(config, speech_name, "speech")
        add_if_local(speech_name)
    return required


def check_required_model_services(config, opener=urlopen) -> list[str]:
    """检查 Agent 所需本地模型的健康接口，失败时给出可执行启动提示。"""
    missing: list[tuple[str, str, str]] = []
    for name in required_local_models(config):
        deployment = config.models[name].settings().get("deployment", {})
        health_url = str(deployment.get("health_url", ""))
        try:
            if not health_url:
                raise RuntimeError("未配置 health_url")
            with opener(health_url, timeout=2) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
        except Exception as error:
            missing.append((name, health_url or "<未配置>", str(error)))
    if missing:
        names = " ".join(name for name, _, _ in missing)
        details = "\n".join(
            f"- {name}: {url} ({error})" for name, url, error in missing
        )
        raise RuntimeError(
            "Agent 所需的本地模型服务不可用：\n"
            f"{details}\n"
            "请先在另一个终端执行：\n"
            f"bash ./llm_agent/scripts/start_models.sh {names}"
        )
    return required_local_models(config)


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
