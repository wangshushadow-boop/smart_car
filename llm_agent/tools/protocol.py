"""Tool implementation contract."""

from __future__ import annotations

from typing import Protocol, Type

from pydantic import BaseModel

from .context import ToolContext


class AgentTool(Protocol):
    name: str
    description: str
    arguments_model: Type[BaseModel]

    def execute(self, arguments: BaseModel, context: ToolContext) -> dict:
        """Execute a validated call and return JSON-compatible data."""
