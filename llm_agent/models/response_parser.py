"""Sanitize user-facing text and parse structured intent decisions."""

from __future__ import annotations

import ast
import json
import math
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


def _normalize_rotation_direction(decision: IntentDecision) -> IntentDecision:
    """把明确的左右语义转换成工具层可稳定处理的方向参数。"""

    if (
        decision.intent != IntentType.ACTION
        or decision.tool_name != "rotate_relative"
        or "angle_deg" not in decision.arguments
    ):
        return decision

    arguments = dict(decision.arguments)
    direction = arguments.get("direction")
    if direction not in {"left", "right", None}:
        return IntentDecision(
            intent=IntentType.UNKNOWN, reason="旋转任务 direction 字段无效"
        )
    if direction is None:
        reason = decision.reason.lower()
        has_left = "左转" in reason or bool(re.search(r"\bturn\s+left\b", reason))
        has_right = "右转" in reason or bool(re.search(r"\bturn\s+right\b", reason))
        if has_left == has_right:
            # 控制实车时不根据含糊的正负号猜方向，宁可拒绝本次动作。
            return IntentDecision(
                intent=IntentType.UNKNOWN, reason="旋转任务没有唯一明确的左右方向"
            )
        direction = "left" if has_left else "right"

    try:
        angle = float(arguments["angle_deg"])
    except (TypeError, ValueError):
        return IntentDecision(
            intent=IntentType.UNKNOWN, reason="旋转任务角度不是有效数值"
        )
    if not math.isfinite(angle):
        return IntentDecision(
            intent=IntentType.UNKNOWN, reason="旋转任务角度不是有限数值"
        )

    arguments["direction"] = direction
    arguments["angle_deg"] = abs(angle)
    return decision.model_copy(update={"arguments": arguments})


def parse_intent_decision(text: str) -> IntentDecision:
    """解析模型结构化输出，并安全兼容单引号 Python 字面量。"""

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return IntentDecision(intent=IntentType.UNKNOWN, reason="模型未返回 JSON")
    raw_object = match.group(0)
    try:
        try:
            payload = json.loads(raw_object)
        except json.JSONDecodeError:
            # MiniCPM 偶尔输出单引号字典；literal_eval 只解析字面量，不执行代码。
            payload = ast.literal_eval(raw_object)
        if not isinstance(payload, dict):
            raise ValueError("意图根节点必须是对象")
        decision = IntentDecision.model_validate(payload)
        return _normalize_rotation_direction(decision)
    except (SyntaxError, ValueError) as error:
        return IntentDecision(intent=IntentType.UNKNOWN, reason=f"意图格式无效：{error}")
