"""Provider 注册表与按配置选择后端的逻辑。

`ProviderRegistry` 是 Provider 工厂的字典视图；`select_backends` 把
`AgentConfig` 翻译成实际可用的 `GenerationBackend` / `SpeechBackend`。
输入理解和语音输出都使用同一种有序模型链：前一个后端失败后尝试下一个。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.request import urlopen

from .protocol import (
    AsrBackend,
    GenerationBackend,
    SpeechBackend,
    SpeechCapabilities,
    SpeechRequest,
    SpeechResponse,
)
from .providers.minicpm import MiniCpmGeneration
from .providers.minimax import MiniMaxGeneration, MiniMaxSpeech
from .providers.piper import PiperSpeech
from .providers.qwen3_asr import Qwen3Asr

GenerationFactory = Callable[[dict], GenerationBackend]
SpeechFactory = Callable[[dict], SpeechBackend]
AsrFactory = Callable[[dict], AsrBackend]


@dataclass(frozen=True)
class MediaRoute:
    """一种媒体的有序 Provider 链与输入限制。"""

    enabled: bool
    max_bytes: int
    max_chars: int
    prompt: str
    backends: tuple[Any, ...]


@dataclass(frozen=True)
class MediaBackends:
    """主模型原生输入能力和非原生媒体理解链。"""

    primary_inputs: frozenset[str]
    audio: MediaRoute
    image: MediaRoute
    video: MediaRoute


class SpeechRoute:
    """语音输出策略与有序后端链。"""

    capabilities = SpeechCapabilities(
        wav_output=True, streaming=False, configurable_voice=True
    )

    def __init__(
        self,
        *,
        enabled: bool,
        auto: str,
        mode: str,
        min_chars: int,
        max_chars: int,
        timeout_seconds: float,
        backends: tuple[SpeechBackend, ...],
    ) -> None:
        self.enabled = enabled
        self.auto = auto
        self.mode = mode
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.timeout_seconds = timeout_seconds
        self.backends = backends
        names = [backend.provider_name for backend in backends]
        self.provider_name = (
            names[0]
            if len(names) == 1
            else ("route:" + "->".join(names) if names else "disabled")
        )

    def synthesize(self, request: SpeechRequest) -> SpeechResponse:
        started_at = monotonic()
        errors: list[str] = []
        for backend in self.backends:
            if monotonic() - started_at >= self.timeout_seconds:
                errors.append(f"总超时 {self.timeout_seconds:g}s")
                break
            try:
                return backend.synthesize(request)
            except Exception as error:
                errors.append(f"{backend.provider_name}: {error}")
        raise RuntimeError("语音模型均不可用：" + "; ".join(errors))


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

    这里仅做配置计算，不创建 Provider。主模型不原生支持的媒体会把配置的
    理解模型加入依赖；启用音频输出时检查整个有序语音模型链。
    """
    required: list[str] = []

    def add_if_local(name: str) -> None:
        model = config.models.get(name)
        if model and model.settings().get("deployment", {}).get("local", False):
            if name not in required:
                required.append(name)

    generation_name = config.generation_model
    generation_model = _model(config, generation_name, "generation_model")
    add_if_local(generation_name)

    for modality in ("audio", "image", "video"):
        selection = getattr(config.modalities.input, modality)
        if not selection.enabled or modality in generation_model.input:
            continue
        role = "asr" if modality == "audio" else "generation_model"
        for name in selection.models:
            media_model = _model(config, name, role)
            if modality not in media_model.input:
                raise ValueError(f"model {name} does not accept {modality} input")
            add_if_local(name)

    speech = config.modalities.output.audio
    if speech.enabled:
        for name in speech.models:
            _model(config, name, "speech")
            add_if_local(name)
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

    返回 `(generation, media, speech)`。输入理解与语音输出均根据配置建立
    有序后端链，模型参数只从 `models.yaml` 读取。
    """
    registry = registry or create_default_registry()
    generation_name = config.generation_model
    generation_model = _model(config, generation_name, "generation_model")
    generation = registry.create_generation(
        generation_model.backend, generation_model.settings()
    )

    def media_route(modality: str) -> MediaRoute:
        selection = getattr(config.modalities.input, modality)
        backends: list[Any] = []
        role = "asr" if modality == "audio" else "generation_model"
        for name in selection.models:
            model = _model(config, name, role)
            if modality not in model.input:
                raise ValueError(f"model {name} does not accept {modality} input")
            if name == generation_name:
                backend = generation
            elif modality == "audio":
                backend = registry.create_asr(model.backend, model.settings())
            else:
                backend = registry.create_generation(model.backend, model.settings())
            backends.append(backend)
        return MediaRoute(
            enabled=selection.enabled,
            max_bytes=selection.max_bytes,
            max_chars=selection.max_chars,
            prompt=selection.prompt,
            backends=tuple(backends),
        )

    media = MediaBackends(
        primary_inputs=frozenset(generation_model.input),
        audio=media_route("audio"),
        image=media_route("image"),
        video=media_route("video"),
    )

    output = config.modalities.output.audio
    speech_backends: list[SpeechBackend] = []
    if output.enabled:
        for name in output.models:
            model = _model(config, name, "speech")
            try:
                speech_backends.append(
                    registry.create_speech(model.backend, model.settings())
                )
            except Exception:
                # 可选云模型缺少密钥时保留后续本地模型；至少一个后端可用即可启动。
                continue
        if not speech_backends:
            raise ValueError("音频输出已启用，但没有可创建的 speech 模型")
    speech = SpeechRoute(
        enabled=output.enabled,
        auto=output.auto,
        mode=output.mode,
        min_chars=output.min_chars,
        max_chars=output.max_chars,
        timeout_seconds=output.timeout_seconds,
        backends=tuple(speech_backends),
    )
    return generation, media, speech
