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

    def test_removes_thinking_before_speech(self) -> None:
        answer = sanitize_spoken_answer("<think>internal</think>回答：你好")
        self.assertEqual(answer, "你好")


if __name__ == "__main__":
    unittest.main()
