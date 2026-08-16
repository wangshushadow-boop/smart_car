from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from llm_agent.skills import (
    MotionSequenceSkill,
    SkillCall,
    SkillRegistry,
    load_skill_directory,
)


class FakeToolRegistry:
    def __init__(self, names: set[str]) -> None:
        self.names = names

    def contains(self, name: str) -> bool:
        return name in self.names


class SkillRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SkillRegistry()
        self.registry.register(MotionSequenceSkill())

    def test_motion_sequence_plans_atomic_tools(self) -> None:
        plan = self.registry.plan(
            SkillCall(
                name="motion_sequence",
                arguments={
                    "steps": [
                        {"action": "move", "distance_m": 1.0},
                        {
                            "action": "rotate",
                            "direction": "right",
                            "angle_deg": 90,
                        },
                    ]
                },
            )
        )

        self.assertEqual(
            [call.name for call in plan.tool_calls],
            ["move_relative", "rotate_relative"],
        )
        self.assertEqual(plan.tool_calls[1].arguments["direction"], "right")

    def test_sequence_requires_at_least_two_steps(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid skill arguments"):
            self.registry.plan(
                SkillCall(
                    name="motion_sequence",
                    arguments={"steps": [{"action": "move", "distance_m": 1}]},
                )
            )

    def test_rejects_mixed_step_parameters(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能包含旋转参数"):
            self.registry.plan(
                SkillCall(
                    name="motion_sequence",
                    arguments={
                        "steps": [
                            {
                                "action": "move",
                                "distance_m": 1,
                                "direction": "left",
                            },
                            {"action": "move", "distance_m": 0.5},
                        ]
                    },
                )
            )

    def test_catalog_exposes_only_summary(self) -> None:
        catalog = self.registry.catalog_prompt()
        self.assertIn("motion_sequence", catalog)
        self.assertNotIn("distance_m", catalog)

    def test_directory_skill_is_discovered_and_rendered(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "inspect_area"
            skill_dir.mkdir()
            (skill_dir / "SKILL.yaml").write_text(
                """
schema: small_car.skill.v1
name: inspect_area
description: 检查指定区域
arguments:
  area_name:
    type: string
    min_length: 1
goal: 检查{{ area_name }}
instructions: 观察{{ area_name }}并报告异常
allowed_tools: [capture_camera]
limits:
  max_steps: 3
  timeout_seconds: 20
  max_total_rotation_deg: 0
  max_total_distance_m: 0
""".strip(),
                encoding="utf-8",
            )
            loaded = load_skill_directory(
                self.registry,
                FakeToolRegistry({"capture_camera"}),
                root,
            )

        self.assertEqual(loaded, 1)
        self.assertTrue(self.registry.is_reactive("inspect_area"))
        task = self.registry.create_task(
            SkillCall(name="inspect_area", arguments={"area_name": "厨房"})
        )
        self.assertEqual(task.goal, "检查厨房")
        self.assertEqual(task.allowed_tools, ["capture_camera"])

    def test_directory_skill_rejects_unknown_tool(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "unsafe_skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.yaml").write_text(
                """
schema: small_car.skill.v1
name: unsafe_skill
description: 非法工具测试
goal: 测试
instructions: 测试
allowed_tools: [publish_any_topic]
""".strip(),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "未注册工具"):
                load_skill_directory(self.registry, FakeToolRegistry(set()), root)


if __name__ == "__main__":
    unittest.main()
