from __future__ import annotations

import unittest

from llm_agent.agent.state import IntentType
from llm_agent.models.response_parser import (
    parse_intent_decision,
    sanitize_spoken_answer,
)


class ResponseParserTest(unittest.TestCase):
    def test_parses_tool_intent_json(self) -> None:
        decision = parse_intent_decision(
            '{"intent":"query","tool_name":"get_robot_status",'
            '"arguments":{},"reason":"查询状态"}'
        )
        self.assertEqual(decision.intent, IntentType.QUERY)
        self.assertEqual(decision.tool_name, "get_robot_status")

    def test_malformed_intent_becomes_unknown(self) -> None:
        decision = parse_intent_decision("not json")
        self.assertEqual(decision.intent, IntentType.UNKNOWN)

    def test_accepts_minicpm_single_quoted_object(self) -> None:
        decision = parse_intent_decision(
            "{'intent':'action','tool_name':'rotate_relative',"
            "'arguments':{'angle_deg':90},'reason':'向右转指令，角度为90度'}"
        )
        self.assertEqual(decision.intent, IntentType.ACTION)
        self.assertEqual(decision.arguments["direction"], "right")
        self.assertEqual(decision.arguments["angle_deg"], 90.0)

    def test_infers_left_direction_from_reason(self) -> None:
        decision = parse_intent_decision(
            '{"intent":"action","tool_name":"rotate_relative",'
            '"arguments":{"angle_deg":-45},"reason":"用户要求向左转"}'
        )
        self.assertEqual(decision.arguments["direction"], "left")
        self.assertEqual(decision.arguments["angle_deg"], 45.0)

    def test_rejects_rotation_without_unambiguous_direction(self) -> None:
        decision = parse_intent_decision(
            "{'intent':'action','tool_name':'rotate_relative',"
            "'arguments':{'angle_deg':90},'reason':'执行旋转'}"
        )
        self.assertEqual(decision.intent, IntentType.UNKNOWN)
        self.assertIn("方向", decision.reason)

    def test_does_not_execute_python_expression(self) -> None:
        decision = parse_intent_decision("{'intent': __import__('os').getcwd()}")
        self.assertEqual(decision.intent, IntentType.UNKNOWN)

    def test_removes_thinking_before_speech(self) -> None:
        answer = sanitize_spoken_answer("<think>internal</think>回答：你好")
        self.assertEqual(answer, "你好")


if __name__ == "__main__":
    unittest.main()
