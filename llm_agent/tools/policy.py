"""Agent 工具权限与任务预算策略。

本模块只回答“某次 ToolCall 是否允许”，不执行工具、不访问模型和 ROS。
Skill 权限、全局物理预算与参数 Schema 在这里汇合，树莓派 Gateway 仍负责
最终硬件安全校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from llm_agent.skills import RobotTask

from .registry import ToolRegistry
from .types import ToolCall


@dataclass(slots=True)
class ToolBudget:
    """一轮 Agent 任务已经消耗的模型步骤和物理运动资源。"""

    started_at: float
    steps: int = 0
    total_rotation_deg: float = 0.0
    total_distance_m: float = 0.0

    @classmethod
    def start(cls) -> "ToolBudget":
        return cls(started_at=monotonic())


class ToolPolicy:
    """计算有效工具白名单，并统一校验任务级软限制。"""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        global_max_steps: int = 30,
        global_timeout_seconds: float = 300.0,
        global_max_rotation_deg: float = 360.0,
        global_max_distance_m: float = 5.0,
    ) -> None:
        self._registry = registry
        self._global_max_steps = global_max_steps
        self._global_timeout_seconds = global_timeout_seconds
        self._global_max_rotation_deg = global_max_rotation_deg
        self._global_max_distance_m = global_max_distance_m

    def allowed_tools(self, task: RobotTask | None = None) -> list[str]:
        """返回本轮真正可见的工具；动态 Skill 只能收窄全局工具面。"""
        names = self._registry.names()
        if task is None:
            return names
        allowed = set(task.allowed_tools)
        return [name for name in names if name in allowed]

    def validate(
        self,
        call: ToolCall,
        budget: ToolBudget,
        task: RobotTask | None = None,
    ) -> str | None:
        """依次检查工具授权、参数 Schema、时间、步骤与累计运动预算。"""
        if call.name not in self.allowed_tools(task):
            return f"工具未获当前任务授权：{call.name}"
        schema_error = self._registry.validate(call)
        if schema_error:
            return schema_error
        if call.name == "rotate_relative" and call.arguments.get("direction") not in {
            "left",
            "right",
        }:
            return "旋转动作必须明确指定 left 或 right"

        max_steps = min(
            self._global_max_steps,
            task.limits.max_steps if task else self._global_max_steps,
        )
        timeout = min(
            self._global_timeout_seconds,
            task.limits.timeout_seconds if task else self._global_timeout_seconds,
        )
        if budget.steps >= max_steps:
            return "任务已达到最大工具步骤数"
        if monotonic() - budget.started_at >= timeout:
            return "任务已超过执行时间限制"

        rotation, distance = self._resource_delta(call)
        rotation_limit = min(
            self._global_max_rotation_deg,
            task.limits.max_total_rotation_deg
            if task
            else self._global_max_rotation_deg,
        )
        distance_limit = min(
            self._global_max_distance_m,
            task.limits.max_total_distance_m
            if task
            else self._global_max_distance_m,
        )
        if budget.total_rotation_deg + rotation > rotation_limit:
            return "累计旋转超过当前任务预算"
        if budget.total_distance_m + distance > distance_limit:
            return "累计移动超过当前任务预算"
        return None

    @staticmethod
    def consume(call: ToolCall, budget: ToolBudget) -> None:
        """工具成功后提交预算，失败调用不消耗物理运动额度。"""
        rotation, distance = ToolPolicy._resource_delta(call)
        budget.steps += 1
        budget.total_rotation_deg += rotation
        budget.total_distance_m += distance

    @staticmethod
    def _resource_delta(call: ToolCall) -> tuple[float, float]:
        if call.name == "rotate_relative":
            return abs(float(call.arguments.get("angle_deg", 0.0))), 0.0
        if call.name == "move_relative":
            return 0.0, abs(float(call.arguments.get("distance_m", 0.0)))
        return 0.0, 0.0
