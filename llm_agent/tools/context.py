"""Restricted dependencies made available to tool implementations."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any


@dataclass(frozen=True)
class ToolContext:
    request_id: str
    cancelled: Event
    services: dict[str, Any]
