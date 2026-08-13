"""Qwen3-ASR-0.6B 惰性语音识别适配器。

Qwen3-ASR 与 MiniCPM/vLLM-Omni 的 transformers 版本约束冲突，因此默认
通过独立 Python 环境中的常驻 Worker 推理。Worker 只在第一次实际转写时
启动；选择原生支持音频的 MiniCPM 时不会创建进程或占用额外显存。
"""

from __future__ import annotations

import json
import os
import select
import subprocess
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

from ..types import TranscriptionRequest, TranscriptionResponse


class Qwen3Asr:
    """通过隔离 Worker 使用 qwen-asr Transformers backend。"""

    provider_name = "qwen3_asr"

    def __init__(
        self,
        settings: dict | None = None,
        *,
        model_path: str | None = None,
        device: str | None = None,
        language: str | None = None,
        worker_python: str | None = None,
        timeout_seconds: float | None = None,
        model_loader: Callable[[], Any] | None = None,
    ) -> None:
        settings = settings or {}
        self._model_path = model_path or os.getenv(
            "QWEN3_ASR_MODEL",
            settings.get("model", "/mnt/d/AI/models/Qwen3-ASR-0.6B"),
        )
        self._device = device or os.getenv(
            "QWEN3_ASR_DEVICE", settings.get("device", "cuda:0")
        )
        self._language = language or os.getenv(
            "QWEN3_ASR_LANGUAGE", settings.get("language", "Chinese")
        )
        self._worker_python = worker_python or os.getenv(
            "QWEN3_ASR_PYTHON",
            settings.get(
                "python",
                "/mnt/d/work/smart_car/llm_agent/py_env/venvs/qwen3-asr/bin/python",
            ),
        )
        self._timeout_seconds = timeout_seconds or float(
            os.getenv(
                "QWEN3_ASR_TIMEOUT_SECONDS",
                str(settings.get("timeout_seconds", 120)),
            )
        )
        # model_loader 只用于依赖无关的单元测试和显式嵌入场景。
        self._model_loader = model_loader
        self._model: Any | None = None
        self._worker: subprocess.Popen[str] | None = None
        self._lock = Lock()

    @property
    def loaded(self) -> bool:
        """仅用于诊断和测试，不触发模型或 Worker 加载。"""
        return self._model is not None or self._worker_alive()

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        audio = [_qwen_audio_input(value) for value in request.audio_data_urls]
        language = request.language or self._language
        with self._lock:
            if self._model_loader is not None:
                return self._transcribe_embedded(audio, language)
            return self._transcribe_worker(audio, language)

    def close(self) -> None:
        """终止当前 Worker；下次请求可重新惰性启动。"""
        with self._lock:
            self._stop_worker()

    def _transcribe_embedded(
        self, audio: list[str], language: str | None
    ) -> TranscriptionResponse:
        if self._model is None:
            self._model = self._model_loader()
        try:
            results = self._model.transcribe(
                audio=audio,
                language=[language] * len(audio) if language else None,
            )
        except Exception as error:
            raise RuntimeError(f"Qwen3 ASR transcription failed: {error}") from error
        return _normalize_results(results, self.provider_name)

    def _transcribe_worker(
        self, audio: list[str], language: str | None
    ) -> TranscriptionResponse:
        worker = self._ensure_worker()
        payload = json.dumps(
            {
                "audio": audio,
                "language": language,
                "model_path": self._model_path,
                "device": self._device,
            },
            ensure_ascii=False,
        )
        try:
            assert worker.stdin is not None
            worker.stdin.write(payload + "\n")
            worker.stdin.flush()
            assert worker.stdout is not None
            readable, _, _ = select.select(
                [worker.stdout], [], [], self._timeout_seconds
            )
            if not readable:
                self._stop_worker()
                raise TimeoutError(
                    f"Qwen3 ASR timed out after {self._timeout_seconds:g} seconds"
                )
            line = worker.stdout.readline()
            if not line:
                code = worker.poll()
                self._stop_worker()
                raise RuntimeError(f"Qwen3 ASR worker exited unexpectedly: {code}")
            result = json.loads(line)
        except (BrokenPipeError, OSError, json.JSONDecodeError) as error:
            self._stop_worker()
            raise RuntimeError(f"Qwen3 ASR worker communication failed: {error}") from error
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        return TranscriptionResponse(
            text=str(result.get("text", "")).strip(),
            provider=self.provider_name,
            language=str(result.get("language", "")),
        )

    def _ensure_worker(self) -> subprocess.Popen[str]:
        if self._worker_alive():
            assert self._worker is not None
            return self._worker
        if not Path(self._worker_python).is_file():
            raise RuntimeError(
                f"Qwen3 ASR Python environment not found: {self._worker_python}"
            )
        project_root = Path(__file__).resolve().parents[2]
        environment = os.environ.copy()
        current_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(project_root), current_pythonpath])
        )
        self._worker = subprocess.Popen(
            [self._worker_python, "-m", "llm_agent.models.qwen3_asr.worker"],
            cwd=project_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # 模型加载日志直接进入 Agent Server stderr，避免管道填满死锁。
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        return self._worker

    def _worker_alive(self) -> bool:
        return self._worker is not None and self._worker.poll() is None

    def _stop_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is None or worker.poll() is not None:
            return
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=5)


def _normalize_results(results, provider: str) -> TranscriptionResponse:
    texts = [str(getattr(result, "text", "")).strip() for result in results]
    text = "\n".join(value for value in texts if value)
    if not text:
        raise RuntimeError("Qwen3 ASR returned empty transcription")
    detected_languages = {
        str(getattr(result, "language", "")).strip()
        for result in results
        if getattr(result, "language", "")
    }
    return TranscriptionResponse(
        text=text,
        provider=provider,
        language=next(iter(detected_languages)) if len(detected_languages) == 1 else "",
    )


def _qwen_audio_input(value: str) -> str:
    """保留 data URL，使 qwen-asr 能可靠识别含斜杠的 base64 音频。"""
    return value
