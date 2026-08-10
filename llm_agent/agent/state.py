"""State shared by LangGraph nodes during one Agent turn."""

from __future__ import annotations

from enum import Enum
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field

from llm_agent.conversation import ConversationTurn
from llm_agent.runtime.contracts import RuntimeRequest


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
    request: RuntimeRequest
    cancel_token: object
    progress_callback: object
    conversation_history: list[ConversationTurn]
    user_summary: str
    intent: IntentDecision
    tool_call: object
    tool_result: object
    command: dict
    answer: str
    answer_wav: bytes
    generation_backend: str
    speech_backend: str
    error: str
