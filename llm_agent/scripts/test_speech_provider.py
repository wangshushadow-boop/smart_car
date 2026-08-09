"""Synthesize a short phrase with a configured speech provider and validate WAV."""

from __future__ import annotations

import argparse
from pathlib import Path

from llm_agent.app.config import load_agent_config
from llm_agent.models.registry import select_backends
from llm_agent.models.types import SpeechRequest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", help="piper, minimax, or auto")
    parser.add_argument("--text", default="语音接口测试")
    parser.add_argument("--output", type=Path, help="optional WAV output path")
    arguments = parser.parse_args()

    config = load_agent_config()
    if arguments.provider:
        config.speech.provider = arguments.provider
    _, speech = select_backends(config)
    response = speech.synthesize(SpeechRequest(text=arguments.text))
    if arguments.output:
        arguments.output.write_bytes(response.audio_wav)
    print(
        f"provider={response.provider} bytes={len(response.audio_wav)} "
        f"sample_rate={response.sample_rate} channels={response.channels}"
    )


if __name__ == "__main__":
    main()
