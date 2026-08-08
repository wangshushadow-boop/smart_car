from __future__ import annotations

import unittest

import numpy as np

from input.playback_echo import PlaybackEchoSuppressor


class PlaybackEchoSuppressorTest(unittest.TestCase):
    def test_reduces_delayed_speaker_echo(self) -> None:
        echo = PlaybackEchoSuppressor(max_delay_ms=500)
        echo.begin_playback()
        # Let the reference stream get ahead of the microphone by 100 ms.
        samples = (np.sin(np.linspace(0, 40, 16_000)) * 9_000).astype("<i2")
        echo.add_playback(samples.tobytes(), 16_000, 1)
        # The actual delay is not important: feed a later chunk which is
        # strongly correlated with something in the reference history.
        original = samples[4_800:5_120].tobytes()
        # Make the test deterministic with a matching elapsed playback clock.
        echo._started_at -= 0.32  # noqa: SLF001 - validates delay search
        cleaned, correlation, ratio = echo.suppress(original, 16_000, 1)
        self.assertGreater(correlation, 0.8)
        self.assertLess(ratio, 0.2)
        self.assertLess(np.abs(np.frombuffer(cleaned, dtype="<i2")).mean(), 100)

    def test_keeps_independent_voice_energy(self) -> None:
        echo = PlaybackEchoSuppressor(max_delay_ms=500)
        echo.begin_playback()
        reference = (np.sin(np.linspace(0, 30, 16_000)) * 8_000).astype("<i2")
        voice = (np.sign(np.sin(np.linspace(0, 120, 320))) * 11_000).astype("<i2")
        echo.add_playback(reference.tobytes(), 16_000, 1)
        echo._started_at -= 0.32  # noqa: SLF001 - validates delay search
        _, correlation, ratio = echo.suppress(voice.tobytes(), 16_000, 1)
        self.assertTrue(echo.is_external_speech(correlation, ratio))


if __name__ == "__main__":
    unittest.main()
