"""Compatibility exports for code that used the former combined client."""

from llm_agent.models.minicpm import MiniCpmModel
from llm_agent.models.response_parser import sanitize_spoken_answer

MiniCpmClient = MiniCpmModel

__all__ = ["MiniCpmClient", "sanitize_spoken_answer"]
