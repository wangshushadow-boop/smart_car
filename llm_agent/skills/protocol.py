"""Skill 实现契约。"""

from __future__ import annotations

from typing import Protocol, Type

from pydantic import BaseModel

from .types import SkillPlan


class AgentSkill(Protocol):
    """Skill 只负责任务编排，不直接访问 ROS 或硬件。"""

    name: str
    description: str
    arguments_model: Type[BaseModel]

    def plan(self, arguments: BaseModel) -> SkillPlan:
        """把已校验的高层参数转换为白名单 Tool 调用计划。"""
