"""State shared by LangGraph nodes during one Agent turn."""

from __future__ import annotations

from enum import Enum
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field

from .events import AgentEvent


class IntentType(str, Enum):
    CHAT = "chat"
    QUERY = "query"
    ACTION = "action"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


class IntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: IntentType
    tool_name: str | None = None
    arguments: dict = Field(default_factory=dict)
    reason: str = ""


class AgentState(TypedDict, total=False):
    request_id: str
    event: AgentEvent
    intent: IntentDecision
    tool_call: object
    tool_result: object
    answer: str
    answer_wav: bytes
    generation_backend: str
    speech_backend: str
    error: str
