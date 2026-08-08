"""Load versioned prompt text from the repository."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromptSet:
    system: str
    intent: str
    response: str
    safety: str


def load_prompts(directory: Path | None = None) -> PromptSet:
    prompt_dir = directory or Path(__file__).resolve().parents[1] / "prompts"

    def read(name: str) -> str:
        path = prompt_dir / f"{name}.txt"
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise RuntimeError(f"cannot load Agent prompt {path}: {error}") from error
        if not value:
            raise RuntimeError(f"Agent prompt is empty: {path}")
        return value

    return PromptSet(
        system=read("system"),
        intent=read("intent"),
        response=read("response"),
        safety=read("safety"),
    )
