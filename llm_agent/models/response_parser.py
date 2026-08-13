"""清洗面向用户的文本，并解析模型返回的 JSON 对象。

包含两个工具函数：
- `sanitize_spoken_answer`：剥离 <think>/工具调用/Markdown 等，只保留可读回答。
- `parse_json_object`：从模型输出中安全抽取一个 JSON/Python 字面量对象。

本模块属于模型边界，因此只处理通用文本格式，不导入 Agent 的意图类型，
也不包含车辆动作规则。意图校验和旋转方向归一化由 Agent 节点负责。
"""

from __future__ import annotations

import ast
import json
import re


def sanitize_spoken_answer(text: str) -> str:
    """只保留最终可读回答，去掉思考标签、Markdown 与工具调用残留。

    处理顺序：
    1. 抽取 `[AI助手]` 段（模型分多段时的最后一段）。
    2. 去掉 `<think>` / `<tool_call>` / ` ```代码块``` ` 等非回答片段。
    3. 去掉前缀 "Assistant:" / "回答：" 等角色标签。
    4. 清理 Markdown 标记和多余空白。
    """

    assistant_segments = re.findall(
        r"\[AI助手\]\s*(?!\[)([^\[\n]+)", text, flags=re.IGNORECASE
    )
    if assistant_segments:
        text = assistant_segments[-1]
    elif re.match(r"\s*<think\b", text, flags=re.IGNORECASE) and not re.search(
        r"</think>", text, flags=re.IGNORECASE
    ):
        # 模型以思考标签开头但没有正确闭合：视为无效回答。
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
    text = re.sub(r"[*`_#>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_json_object(text: str) -> dict:
    """解析模型结构化输出，并安全兼容单引号 Python 字面量。

    解码顺序：
    1. 去掉 ```json ... ``` 包裹。
    2. 用正则提取第一对 `{...}`。
    3. 优先 `json.loads`；失败时尝试 `ast.literal_eval`（处理 MiniCPM 偶发
       的单引号字典输出），且 `literal_eval` 只解析字面量不执行代码。
    4. 根节点不是对象或内容无效时抛出 ``ValueError``，由调用方决定降级策略。
    """

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("模型未返回 JSON 对象")
    raw_object = match.group(0)
    try:
        try:
            payload = json.loads(raw_object)
        except json.JSONDecodeError:
            # MiniCPM 偶尔输出单引号字典；literal_eval 只解析字面量，不执行代码。
            payload = ast.literal_eval(raw_object)
        if not isinstance(payload, dict):
            raise ValueError("模型输出根节点必须是对象")
        return payload
    except (SyntaxError, ValueError) as error:
        raise ValueError(f"模型输出格式无效：{error}") from error
