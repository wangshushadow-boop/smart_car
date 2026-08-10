"""Skill 白名单、参数校验和任务计划生成。"""

from __future__ import annotations

from pydantic import ValidationError

from .protocol import AgentSkill
from .types import SkillCall, SkillPlan


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, AgentSkill] = {}

    def register(self, skill: AgentSkill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"skill already registered: {skill.name}")
        self._skills[skill.name] = skill

    def contains(self, name: str) -> bool:
        return name in self._skills

    def catalog_prompt(self) -> str:
        """只暴露简短目录，避免把所有 Skill 细节常驻模型上下文。"""
        if not self._skills:
            return ""
        lines = ["可用 Skill："]
        for skill in self._skills.values():
            lines.append(f"- {skill.name}: {skill.description}")
        return "\n".join(lines)

    def plan(self, call: SkillCall) -> SkillPlan:
        skill = self._skills.get(call.name)
        if skill is None:
            raise ValueError(f"skill is not registered: {call.name}")
        try:
            arguments = skill.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            raise ValueError(f"invalid skill arguments: {error}") from error
        return skill.plan(arguments)
