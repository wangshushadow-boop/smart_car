from __future__ import annotations

import unittest

from llm_agent.sessions import (
    InMemoryConversationStore,
    format_conversation_history,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class ConversationStoreTest(unittest.TestCase):
    def test_sessions_are_isolated_and_can_be_cleared(self) -> None:
        store = InMemoryConversationStore()
        store.append_turn("web", "你好", "你好")
        store.append_turn("pi", "状态", "空闲")

        self.assertEqual(store.recent("web")[0].user_text, "你好")
        self.assertEqual(store.recent("pi")[0].user_text, "状态")
        store.clear("web")
        self.assertEqual(store.recent("web"), [])
        self.assertEqual(len(store.recent("pi")), 1)

    def test_keeps_only_latest_turns(self) -> None:
        store = InMemoryConversationStore(max_turns=2)
        store.append_turn("session", "一", "答一")
        store.append_turn("session", "二", "答二")
        store.append_turn("session", "三", "答三")

        self.assertEqual(
            [turn.user_text for turn in store.recent("session")], ["二", "三"]
        )

    def test_expires_session_after_ttl(self) -> None:
        clock = FakeClock()
        store = InMemoryConversationStore(ttl_seconds=10, clock=clock)
        store.append_turn("session", "问题", "回答")
        clock.now = 9.9
        self.assertEqual(len(store.recent("session")), 1)
        clock.now = 10.0
        self.assertEqual(store.recent("session"), [])

    def test_context_character_budget_prefers_latest_turn(self) -> None:
        store = InMemoryConversationStore(max_context_chars=8)
        store.append_turn("session", "旧问题", "旧回答")
        store.append_turn("session", "新问题", "新回答")

        turns = store.recent("session")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].user_text, "新问题")

    def test_evicts_oldest_session_when_capacity_is_full(self) -> None:
        clock = FakeClock()
        store = InMemoryConversationStore(max_sessions=2, clock=clock)
        store.append_turn("one", "1", "1")
        clock.now = 1
        store.append_turn("two", "2", "2")
        clock.now = 2
        store.append_turn("three", "3", "3")

        self.assertEqual(store.recent("one"), [])
        self.assertEqual(len(store.recent("two")), 1)
        self.assertEqual(len(store.recent("three")), 1)

    def test_formats_history_with_motion_safety_boundary(self) -> None:
        store = InMemoryConversationStore()
        store.append_turn("session", "向前一米", "准备前进一米")
        history = format_conversation_history(store.recent("session"))
        self.assertIn("不得复用历史运动参数", history)
        self.assertIn("用户：向前一米", history)
        self.assertIn("助手：准备前进一米", history)


if __name__ == "__main__":
    unittest.main()
