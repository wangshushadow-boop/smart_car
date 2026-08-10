"""从仓库加载版本化的 Prompt 文本。

Prompt 全部以纯文本形式提交到 `llm_agent/prompts/`，便于按 commit 评审
提示词变更。本模块负责按名称读取 4 类 Prompt：
- `system`：系统级身份与安全约束，所有节点共用。
- `intent`：意图分类提示，仅 `understand_intent` 节点使用。
- `response`：自然语言回复提示，仅 `generate_response` 节点使用。
- `safety`：回复阶段的安全附加约束，避免模型给出危险建议。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromptSet:
    """Agent 一轮请求会用到的全部 Prompt 集合（不可变）。"""

    system: str
    intent: str
    response: str
    safety: str


def load_prompts(directory: Path | None = None) -> PromptSet:
    """加载所有 Prompt，缺失或为空时直接抛错拒绝启动。"""
    prompt_dir = directory or Path(__file__).resolve().parents[1] / "prompts"

    def read(name: str) -> str:
        path = prompt_dir / f"{name}.txt"
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise RuntimeError(f"cannot load Agent prompt {path}: {error}") from error
        if not value:
            # 空的 Prompt 等同于无安全约束，宁可启动失败也不要带病运行。
            raise RuntimeError(f"Agent prompt is empty: {path}")
        return value

    return PromptSet(
        system=read("system"),
        intent=read("intent"),
        response=read("response"),
        safety=read("safety"),
    )
