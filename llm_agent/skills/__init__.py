"""可按需选择的高层任务技能包。

`skills/` 层只做参数校验与 Tool 调用计划展开，不接触 ROS、模型或硬件。
所有对外暴露类型与 Skill 都在这里集中 re-export。
"""

from .motion_sequence import MotionSequenceSkill
from .registry import SkillRegistry
from .types import SkillCall, SkillPlan, SkillPlanResult

__all__ = [
    "MotionSequenceSkill",
    "SkillCall",
    "SkillPlan",
    "SkillPlanResult",
    "SkillRegistry",
]
