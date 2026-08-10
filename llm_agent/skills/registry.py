"""Skill 白名单、参数校验和任务计划生成。

`SkillRegistry` 与 `ToolRegistry` 结构相似，但职责不同：
- Tool Registry 负责"单个原子动作"的参数校验与线程池执行。
- Skill Registry 负责"高层参数 → 一组 Tool 调用"的展开与白名单校验。
"""

from __future__ import annotations

from pydantic import ValidationError

from .protocol import AgentSkill
from .types import SkillCall, SkillPlan


class SkillRegistry:
    """Skill 实例的统一注册与查找表。"""

    def __init__(self) -> None:
        self._skills: dict[str, AgentSkill] = {}

    def register(self, skill: AgentSkill) -> None:
        """注册 Skill；同名重复注册直接抛错。"""
        if skill.name in self._skills:
            raise ValueError(f"skill already registered: {skill.name}")
        self._skills[skill.name] = skill

    def contains(self, name: str) -> bool:
        """白名单查询；`skill_safety_check` 节点用此快速拦截非法 Skill。"""
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
        """展开 Skill 调用：白名单校验 → 参数 Pydantic 校验 → 调用 `skill.plan()`。"""
        skill = self._skills.get(call.name)
        if skill is None:
            raise ValueError(f"skill is not registered: {call.name}")
        try:
            arguments = skill.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            raise ValueError(f"invalid skill arguments: {error}") from error
        return skill.plan(arguments)
