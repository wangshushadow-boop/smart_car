"""Playback-reference echo suppression for the full-duplex voice path.

The microphone and speaker are on the Raspberry Pi, while the Agent runs in
WSL.  This module therefore deliberately uses the audio being sent to the
speaker as its reference instead of relying on wall-clock timestamps from two
machines.  It searches a short, bounded delay range for every 20 ms microphone
frame and removes the best correlated speaker component.
"""
from __future__ import annotations

import audioop
import time
from threading import Lock

import numpy as np


class PlaybackEchoSuppressor:
    """Suppress speaker echo and identify microphone speech during playback.

    This is a deliberately conservative single-channel adaptive canceller.  It
    does not claim to replace a hardware/WebRTC AEC, but it is enough to keep
    the robot listening continuously and make a real nearby voice interrupt
    TTS without feeding ordinary speaker audio back to the Agent.
    """

    def __init__(
        self,
        sample_rate: int = 16_000,
        max_delay_ms: int = 500,
        tail_ms: int = 500,
    ) -> None:
        self._sample_rate = sample_rate
        self._max_delay_samples = sample_rate * max_delay_ms // 1000
        self._tail_seconds = tail_ms / 1000.0
        self._lock = Lock()
        self._reference = np.empty(0, dtype=np.float32)
        self._started_at: float | None = None
        self._finished_at: float | None = None

    def begin_playback(self) -> None:
        with self._lock:
            self._reference = np.empty(0, dtype=np.float32)
            self._started_at = time.monotonic()
            self._finished_at = None

    def finish_playback(self) -> None:
        with self._lock:
            self._finished_at = time.monotonic()

    def add_playback(self, pcm: bytes, sample_rate: int, channels: int) -> None:
        """Append PCM that is about to be sent to the physical speaker."""
        if not pcm or sample_rate <= 0 or channels <= 0:
            return
        if channels == 2:
            pcm = audioop.tomono(pcm, 2, 0.5, 0.5)
        elif channels != 1:
            return
        if sample_rate != self._sample_rate:
            pcm, _ = audioop.ratecv(pcm, 2, 1, sample_rate, self._sample_rate, None)
        if not pcm:
            return
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32, copy=True)
        with self._lock:
            if self._started_at is None:
                return
            self._reference = np.concatenate((self._reference, samples))

    def suppress(self, pcm: bytes, sample_rate: int, channels: int) -> tuple[bytes, float, float]:
        """Return ``(residual_pcm, correlation, residual_energy_ratio)``.

        The delay scan also absorbs network, USB and ALSA buffering delay.  A
        residual ratio near zero means the input was almost entirely speaker
        echo; a ratio near one means it contains independent sound.
        """
        if sample_rate != self._sample_rate or channels != 1 or not pcm:
            return pcm, 0.0, 1.0
        microphone = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        if microphone.size == 0:
            return pcm, 0.0, 1.0
        now = time.monotonic()
        with self._lock:
            if self._started_at is None:
                return pcm, 0.0, 1.0
            if self._finished_at is not None and now - self._finished_at > self._tail_seconds:
                return pcm, 0.0, 1.0
            reference = self._reference.copy()
            played_samples = int((now - self._started_at) * self._sample_rate)

        best_reference: np.ndarray | None = None
        best_correlation = 0.0
        microphone_norm = float(np.linalg.norm(microphone))
        if microphone_norm < 1.0:
            return pcm, 0.0, 1.0
        # 20 ms steps are sufficient because input frames are also 20 ms.  The
        # scan is bounded to prevent old utterances from being matched.
        for delay in range(0, self._max_delay_samples + 1, microphone.size):
            end = played_samples - delay
            start = end - microphone.size
            if start < 0 or end > reference.size:
                continue
            candidate = reference[start:end]
            candidate_norm = float(np.linalg.norm(candidate))
            if candidate_norm < 1.0:
                continue
            correlation = float(np.dot(microphone, candidate) / (microphone_norm * candidate_norm))
            if correlation > best_correlation:
                best_correlation = correlation
                best_reference = candidate

        if best_reference is None or best_correlation < 0.35:
            return pcm, best_correlation, 1.0
        gain = float(np.dot(microphone, best_reference) / (np.dot(best_reference, best_reference) + 1.0))
        # A real acoustic path is positive and cannot plausibly amplify by an
        # arbitrary amount.  Bounding gain makes external speech safe.
        gain = min(3.0, max(0.0, gain))
        residual = microphone - gain * best_reference
        residual_ratio = float(np.linalg.norm(residual) / microphone_norm)
        cleaned = np.clip(np.rint(residual), -32768, 32767).astype("<i2")
        return cleaned.tobytes(), best_correlation, residual_ratio

    @staticmethod
    def is_external_speech(correlation: float, residual_ratio: float) -> bool:
        """Classify sound remaining after cancellation as a likely human voice."""
        return correlation < 0.60 or residual_ratio >= 0.45
