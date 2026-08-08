"""Typed events accepted by the Agent runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AgentEvent(BaseModel):
    """Base type shared by every event entering the Agent."""

    model_config = ConfigDict(extra="forbid")

    event: str
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SpeechFinished(AgentEvent):
    event: Literal["speech_finished"] = "speech_finished"
    speech_wav: bytes
    perception: dict[str, Any] = Field(default_factory=dict)


class TextReceived(AgentEvent):
    event: Literal["text_received"] = "text_received"
    text: str
    perception: dict[str, Any] = Field(default_factory=dict)


class BargeIn(AgentEvent):
    event: Literal["barge_in"] = "barge_in"


class TaskCancelled(AgentEvent):
    event: Literal["task_cancelled"] = "task_cancelled"
    reason: str = "user_request"


class RobotFault(AgentEvent):
    event: Literal["robot_fault"] = "robot_fault"
    code: str
    message: str


def event_from_legacy(value: AgentEvent | dict[str, Any]) -> AgentEvent:
    """Convert the original dictionary event format during the migration."""

    if isinstance(value, AgentEvent):
        return value
    event_type = value.get("event")
    event_types = {
        "speech_finished": SpeechFinished,
        "text_received": TextReceived,
        "barge_in": BargeIn,
        "task_cancelled": TaskCancelled,
        "robot_fault": RobotFault,
    }
    model = event_types.get(event_type)
    if model is None:
        raise ValueError(f"unsupported Agent event: {event_type!r}")
    return model.model_validate(value)
