"""线程安全、容量受限的短期会话上下文。

设计目标：
- 多客户端独立 session_id，互不干扰。
- 自动按 TTL 失效、按字符预算截断，避免撑爆 Prompt。
- 不存储音频/图片/视频二进制，只保留文字往返。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """一轮纯文字会话；不保存音频、图片或视频二进制。"""

    user_text: str
    assistant_text: str
    created_at: float


class ConversationStore(Protocol):
    """Runtime 使用的短期对话存储接口，可由 SQLite/Redis 实现替换。"""

    def recent(self, session_id: str) -> list[ConversationTurn]:
        """返回指定会话按时间正序排列的最近对话。"""

    def append_turn(
        self, session_id: str, user_text: str, assistant_text: str
    ) -> None:
        """追加一轮会话。"""

    def clear(self, session_id: str) -> None:
        """清空指定会话。"""


class NullConversationStore:
    """关闭多轮上下文时使用的空实现。"""

    def recent(self, session_id: str) -> list[ConversationTurn]:
        del session_id
        return []

    def append_turn(
        self, session_id: str, user_text: str, assistant_text: str
    ) -> None:
        del session_id, user_text, assistant_text

    def clear(self, session_id: str) -> None:
        del session_id


class InMemoryConversationStore:
    """使用内存保存有限会话，进程退出后自动释放。

    关键约束：
    - 同一时刻只有一个 session 可写入（用 `_lock` 串行化）。
    - TTL 与容量在每次访问时按需清理，无需后台线程。
    - 字符预算超出时优先保留最新一轮。
    """

    def __init__(
        self,
        *,
        max_turns: int = 8,
        max_context_chars: int = 12_000,
        ttl_seconds: float = 1800.0,
        max_sessions: int = 128,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if (
            max_turns <= 0
            or max_context_chars <= 0
            or ttl_seconds <= 0
            or max_sessions <= 0
        ):
            raise ValueError("会话容量、上下文长度和 TTL 必须为正数")
        self._max_turns = max_turns
        self._max_context_chars = max_context_chars
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._clock = clock
        # session_id -> 最近 N 轮对话（deque 自动截断）。
        self._sessions: dict[str, deque[ConversationTurn]] = {}
        self._lock = Lock()

    def recent(self, session_id: str) -> list[ConversationTurn]:
        """读取最近对话并按字符预算裁剪；空 session_id 直接返回空列表。"""
        if not session_id:
            return []
        with self._lock:
            now = self._clock()
            self._prune_expired_locked(now)
            turns = self._sessions.get(session_id)
            if not turns:
                return []
            return self._fit_context(list(turns))

    def append_turn(
        self, session_id: str, user_text: str, assistant_text: str
    ) -> None:
        """追加一轮对话；空文本或空 session_id 直接忽略。"""
        user_text = user_text.strip()
        assistant_text = assistant_text.strip()
        if not session_id or not (user_text or assistant_text):
            return
        with self._lock:
            now = self._clock()
            self._prune_expired_locked(now)
            if session_id not in self._sessions:
                self._evict_oldest_session_locked()
                self._sessions[session_id] = deque(maxlen=self._max_turns)
            self._sessions[session_id].append(
                ConversationTurn(
                    user_text=user_text,
                    assistant_text=assistant_text,
                    created_at=now,
                )
            )

    def clear(self, session_id: str) -> None:
        """清空指定会话；空 session_id 静默忽略。"""
        if not session_id:
            return
        with self._lock:
            self._sessions.pop(session_id, None)

    def _prune_expired_locked(self, now: float) -> None:
        """清掉已超过 TTL 的全部会话（按最后活跃时间判断）。"""
        expired = [
            session_id
            for session_id, turns in self._sessions.items()
            if not turns or now - turns[-1].created_at >= self._ttl_seconds
        ]
        for session_id in expired:
            del self._sessions[session_id]

    def _evict_oldest_session_locked(self) -> None:
        """超出 `max_sessions` 时驱逐最久未活跃的会话。"""
        if len(self._sessions) < self._max_sessions:
            return
        oldest = min(
            self._sessions,
            key=lambda session_id: self._sessions[session_id][-1].created_at,
        )
        del self._sessions[oldest]

    def _fit_context(self, turns: list[ConversationTurn]) -> list[ConversationTurn]:
        """按字符预算从最新一轮往前取，必要时裁剪最早一轮。"""
        selected: list[ConversationTurn] = []
        used_chars = 0
        for turn in reversed(turns):
            turn_chars = len(turn.user_text) + len(turn.assistant_text)
            if selected and used_chars + turn_chars > self._max_context_chars:
                break
            if not selected and turn_chars > self._max_context_chars:
                # 第一轮本身就超过预算时也要返回（截断到预算）。
                turn = self._truncate_turn(turn, self._max_context_chars)
                turn_chars = len(turn.user_text) + len(turn.assistant_text)
            selected.append(turn)
            used_chars += turn_chars
        selected.reverse()
        return selected

    @staticmethod
    def _truncate_turn(turn: ConversationTurn, budget: int) -> ConversationTurn:
        """单轮文本截断：用户/助手各占一半预算（实际按内容长度自适应）。"""
        user_budget = min(len(turn.user_text), budget // 2)
        assistant_budget = max(0, budget - user_budget)
        return ConversationTurn(
            user_text=turn.user_text[:user_budget],
            assistant_text=turn.assistant_text[:assistant_budget],
            created_at=turn.created_at,
        )


def format_conversation_history(turns: list[ConversationTurn]) -> str:
    """把历史转成 Provider 无关的纯文本上下文（仅供模型理解，不用于控制）。"""

    if not turns:
        return ""
    # 显式提醒模型：历史只用于理解上下文，不要从中复用运动参数控制车辆。
    lines = [
        "最近对话（只用于理解当前问答；不得复用历史运动参数控制车辆）："
    ]
    for turn in turns:
        if turn.user_text:
            lines.append(f"用户：{turn.user_text}")
        if turn.assistant_text:
            lines.append(f"助手：{turn.assistant_text}")
    return "\n".join(lines)
