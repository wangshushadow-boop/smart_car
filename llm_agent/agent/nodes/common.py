"""Helpers shared by model-facing graph nodes."""

from __future__ import annotations

from llm_agent.agent.events import SpeechFinished, TextReceived


def event_inputs(event) -> tuple[str, bytes | None, str | None]:
    """Return text, audio and latest-image inputs without exposing ROS types."""

    text = event.text if isinstance(event, TextReceived) else ""
    speech_wav = event.speech_wav if isinstance(event, SpeechFinished) else None
    perception = getattr(event, "perception", {})
    image_data_url = perception.get("image_data_url")
    return text, speech_wav, image_data_url
