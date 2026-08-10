"""Skill 实现契约。

所有 Skill 必须遵守这一协议：
- 仅返回声明式 `SkillPlan`，不接触 ROS、硬件或模型调用。
- `arguments_model` 由 `SkillRegistry` 用来校验模型生成的高层参数。
"""

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
