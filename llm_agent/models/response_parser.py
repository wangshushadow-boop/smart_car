"""Sanitize user-facing text and parse structured intent decisions."""

from __future__ import annotations

import json
import re

from llm_agent.agent.state import IntentDecision, IntentType


def sanitize_spoken_answer(text: str) -> str:
    """Keep only the final user-facing answer before speech synthesis."""

    assistant_segments = re.findall(
        r"\[AI助手\]\s*(?!\[)([^\[\n]+)", text, flags=re.IGNORECASE
    )
    if assistant_segments:
        text = assistant_segments[-1]
    elif re.match(r"\s*<think\b", text, flags=re.IGNORECASE) and not re.search(
        r"</think>", text, flags=re.IGNORECASE
    ):
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"<(?:tool|function|analysis|commentary)[^>]*>.*?</(?:tool|function|analysis|commentary)>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(
        r"^\s*(?:assistant|final(?:_answer)?|回答|答复)\s*[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[`*_#>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_intent_decision(text: str) -> IntentDecision:
    """Parse strict JSON, falling back to an unknown intent on malformed output."""

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return IntentDecision(intent=IntentType.UNKNOWN, reason="模型未返回 JSON")
    try:
        payload = json.loads(match.group(0))
        return IntentDecision.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as error:
        return IntentDecision(intent=IntentType.UNKNOWN, reason=f"意图格式无效：{error}")
