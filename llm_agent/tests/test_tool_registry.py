from __future__ import annotations

import unittest
import time
from threading import Event

from pydantic import BaseModel

from llm_agent.tools.context import ToolContext
from llm_agent.tools.registry import ToolRegistry
from llm_agent.tools.types import ToolCall
from llm_agent.tools.vehicle.status import GetRobotStatusTool, RobotStatus


class FakeStatusProvider:
    def __init__(self) -> None:
        self.calls = 0

    def get_status(self) -> RobotStatus:
        self.calls += 1
        return RobotStatus(
            available=True,
            motion_state="idle",
            battery_percentage=82.0,
        )


class NoArguments(BaseModel):
    pass


class SlowTool:
    name = "slow"
    description = "test timeout"
    arguments_model = NoArguments
    timeout_seconds = 0.01

    def execute(self, arguments, context) -> dict:
        del arguments, context
        time.sleep(0.05)
        return {}


class ToolRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = FakeStatusProvider()
        self.registry = ToolRegistry()
        self.registry.register(GetRobotStatusTool(self.provider))
        self.context = ToolContext("request", Event(), {})

    def test_executes_registered_tool(self) -> None:
        result = self.registry.execute(
            ToolCall(name="get_robot_status", arguments={}), self.context
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["battery_percentage"], 82.0)
        self.assertEqual(self.provider.calls, 1)

    def test_rejects_unknown_tool(self) -> None:
        result = self.registry.execute(
            ToolCall(name="publish_any_topic", arguments={}), self.context
        )
        self.assertFalse(result.success)
        self.assertEqual(self.provider.calls, 0)

    def test_rejects_invalid_arguments(self) -> None:
        result = self.registry.execute(
            ToolCall(name="get_robot_status", arguments={"unexpected": True}),
            self.context,
        )
        self.assertFalse(result.success)
        self.assertEqual(self.provider.calls, 0)

    def test_validate_does_not_execute_tool(self) -> None:
        error = self.registry.validate(
            ToolCall(name="get_robot_status", arguments={})
        )
        self.assertIsNone(error)
        self.assertEqual(self.provider.calls, 0)

    def test_times_out_slow_tool(self) -> None:
        self.registry.register(SlowTool())
        result = self.registry.execute(
            ToolCall(name="slow", arguments={}), self.context
        )
        self.assertFalse(result.success)
        self.assertIn("timed out", result.error)


if __name__ == "__main__":
    unittest.main()
