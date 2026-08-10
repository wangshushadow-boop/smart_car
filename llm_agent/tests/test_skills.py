from __future__ import annotations

import unittest

from llm_agent.skills import MotionSequenceSkill, SkillCall, SkillRegistry


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


if __name__ == "__main__":
    unittest.main()
