from __future__ import annotations

import unittest

from llm_agent.tools.vehicle.motion import (
    RotateRelativeArguments,
    RotateRelativeTool,
)


class MotionToolsTest(unittest.TestCase):
    def test_right_direction_becomes_negative_protocol_angle(self) -> None:
        arguments = RotateRelativeArguments(angle_deg=90, direction="right")
        command = RotateRelativeTool().execute(arguments, None)
        self.assertEqual(command["angle_deg"], -90)

    def test_left_direction_becomes_positive_protocol_angle(self) -> None:
        arguments = RotateRelativeArguments(angle_deg=90, direction="left")
        command = RotateRelativeTool().execute(arguments, None)
        self.assertEqual(command["angle_deg"], 90)

    def test_signed_legacy_angle_remains_compatible(self) -> None:
        arguments = RotateRelativeArguments(angle_deg=-30)
        command = RotateRelativeTool().execute(arguments, None)
        self.assertEqual(command["angle_deg"], -30)


if __name__ == "__main__":
    unittest.main()
