"""Transcribe a local audio file with the configured Qwen3-ASR adapter."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

from llm_agent.asr.qwen3 import Qwen3Asr
from llm_agent.asr.types import TranscriptionRequest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path, help="audio file to transcribe")
    parser.add_argument("--language", help="optional language hint, for example Chinese")
    arguments = parser.parse_args()

    suffix = arguments.input.suffix.lower()
    mime_type = "audio/wav" if suffix == ".wav" else "application/octet-stream"
    encoded = base64.b64encode(arguments.input.read_bytes()).decode("ascii")
    audio_data_url = f"data:{mime_type};base64,{encoded}"

    backend = Qwen3Asr()
    try:
        response = backend.transcribe(
            TranscriptionRequest(
                audio_data_urls=[audio_data_url],
                language=arguments.language,
            )
        )
    finally:
        backend.close()

    print(
        f"provider={response.provider} language={response.language or 'auto'} "
        f"text={response.text}"
    )


if __name__ == "__main__":
    main()
