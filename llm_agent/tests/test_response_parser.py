from __future__ import annotations

import unittest

from llm_agent.models.protocol import parse_json_object, sanitize_spoken_answer


class ResponseParserTest(unittest.TestCase):
    def test_parses_json_object(self) -> None:
        payload = parse_json_object(
            '{"intent":"query","tool_name":"get_robot_status",'
            '"arguments":{},"reason":"查询状态"}'
        )
        self.assertEqual(payload["intent"], "query")
        self.assertEqual(payload["tool_name"], "get_robot_status")

    def test_malformed_output_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON"):
            parse_json_object("not json")

    def test_accepts_minicpm_single_quoted_object(self) -> None:
        payload = parse_json_object(
            "{'intent':'action','tool_name':'rotate_relative',"
            "'arguments':{'angle_deg':90},'reason':'向右转指令，角度为90度'}"
        )
        self.assertEqual(payload["intent"], "action")
        self.assertEqual(payload["arguments"]["angle_deg"], 90)

    def test_does_not_execute_python_expression(self) -> None:
        with self.assertRaisesRegex(ValueError, "格式无效"):
            parse_json_object("{'intent': __import__('os').getcwd()}")

    def test_removes_thinking_before_speech(self) -> None:
        answer = sanitize_spoken_answer("<think>internal</think>回答：你好")
        self.assertEqual(answer, "你好")


if __name__ == "__main__":
    unittest.main()
