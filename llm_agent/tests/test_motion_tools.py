from __future__ import annotations

import unittest
from threading import Event

from llm_agent.tools.vehicle.motion import (
    MoveRelativeArguments,
    MoveRelativeTool,
    RotateRelativeArguments,
    RotateRelativeTool,
)
from llm_agent.tools.types import ToolContext


class FakeRobotToolClient:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, tool_name, arguments, **kwargs):
        self.calls.append((tool_name, arguments, kwargs))
        return {"schema": "small_car.tool_result.v1", "executed": True}


class MotionToolsTest(unittest.TestCase):
    def test_injected_client_executes_instead_of_returning_motion_task(self) -> None:
        client = FakeRobotToolClient()
        context = ToolContext("task-1", Event(), {})
        result = MoveRelativeTool(client).execute(
            MoveRelativeArguments(distance_m=0.2), context
        )
        self.assertTrue(result["executed"])
        self.assertEqual(client.calls[0][0], "move_relative")
        self.assertEqual(client.calls[0][1], {"distance_m": 0.2})
        self.assertEqual(client.calls[0][2]["task_id"], "task-1")

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
