"""SQLite SessionStore。

该存储同时实现现有 ConversationStore 接口，并额外记录每次 Agent Run 与
Tool/Skill 执行轨迹。数据库只保存文字和结构化 JSON，不保存音频、图片原文。
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import monotonic, time
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """一轮纯文字会话；不持久化音频、图片或视频。"""

    user_text: str
    assistant_text: str
    created_at: float


class ConversationStore(Protocol):
    """AgentRuntime 使用的最小会话存储接口。"""

    def recent(self, session_id: str) -> list[ConversationTurn]: ...

    def append_turn(self, session_id: str, user_text: str, assistant_text: str) -> None: ...

    def clear(self, session_id: str) -> None: ...


class NullConversationStore:
    """关闭多轮上下文时使用的空实现。"""

    def recent(self, session_id: str) -> list[ConversationTurn]:
        del session_id
        return []

    def append_turn(self, session_id: str, user_text: str, assistant_text: str) -> None:
        del session_id, user_text, assistant_text

    def clear(self, session_id: str) -> None:
        del session_id


class InMemoryConversationStore:
    """线程安全、容量和 TTL 受限的内存会话存储。"""

    def __init__(
        self,
        *,
        max_turns: int = 8,
        max_context_chars: int = 12_000,
        ttl_seconds: float = 1800.0,
        max_sessions: int = 128,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if min(max_turns, max_context_chars, ttl_seconds, max_sessions) <= 0:
            raise ValueError("会话容量、上下文长度和 TTL 必须为正数")
        self._max_turns = max_turns
        self._max_context_chars = max_context_chars
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._clock = clock
        self._sessions: dict[str, deque[ConversationTurn]] = {}
        self._lock = Lock()

    def recent(self, session_id: str) -> list[ConversationTurn]:
        if not session_id:
            return []
        with self._lock:
            self._prune_expired_locked(self._clock())
            turns = self._sessions.get(session_id)
            return self._fit_context(list(turns)) if turns else []

    def append_turn(self, session_id: str, user_text: str, assistant_text: str) -> None:
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
                ConversationTurn(user_text, assistant_text, now)
            )

    def clear(self, session_id: str) -> None:
        if session_id:
            with self._lock:
                self._sessions.pop(session_id, None)

    def _prune_expired_locked(self, now: float) -> None:
        expired = [
            key for key, turns in self._sessions.items()
            if not turns or now - turns[-1].created_at >= self._ttl_seconds
        ]
        for key in expired:
            del self._sessions[key]

    def _evict_oldest_session_locked(self) -> None:
        if len(self._sessions) >= self._max_sessions:
            oldest = min(self._sessions, key=lambda key: self._sessions[key][-1].created_at)
            del self._sessions[oldest]

    def _fit_context(self, turns: list[ConversationTurn]) -> list[ConversationTurn]:
        selected: list[ConversationTurn] = []
        used = 0
        for turn in reversed(turns):
            size = len(turn.user_text) + len(turn.assistant_text)
            if selected and used + size > self._max_context_chars:
                break
            if not selected and size > self._max_context_chars:
                user_budget = min(len(turn.user_text), self._max_context_chars // 2)
                assistant_budget = self._max_context_chars - user_budget
                turn = ConversationTurn(
                    turn.user_text[:user_budget],
                    turn.assistant_text[:assistant_budget],
                    turn.created_at,
                )
                size = len(turn.user_text) + len(turn.assistant_text)
            selected.append(turn)
            used += size
        return list(reversed(selected))


def format_conversation_history(turns: list[ConversationTurn]) -> str:
    """把历史转成只用于理解、不允许复用运动参数的模型上下文。"""
    if not turns:
        return ""
    lines = ["最近对话（只用于理解当前问答；不得复用历史运动参数控制车辆）："]
    for turn in turns:
        if turn.user_text:
            lines.append(f"用户：{turn.user_text}")
        if turn.assistant_text:
            lines.append(f"助手：{turn.assistant_text}")
    return "\n".join(lines)


class SQLiteSessionStore:
    """线程安全、容量受限、可跨 Agent 重启恢复的会话存储。"""

    def __init__(
        self,
        path: str | Path,
        *,
        max_turns: int = 8,
        max_context_chars: int = 12_000,
        ttl_seconds: float = 1800.0,
        max_sessions: int = 128,
    ) -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_turns = max_turns
        self._max_context_chars = max_context_chars
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._lock = Lock()
        self._connection = sqlite3.connect(
            self._path, check_same_thread=False, timeout=5.0
        )
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def recent(self, session_id: str) -> list[ConversationTurn]:
        """读取有效 Session 的最近文字轮次，并按字符预算从后向前裁剪。"""
        if not session_id:
            return []
        with self._lock, self._connection:
            self._prune_locked()
            rows = self._connection.execute(
                """
                SELECT user_text, assistant_text, created_at
                FROM conversation_turns
                WHERE session_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (session_id, self._max_turns),
            ).fetchall()
        turns = [ConversationTurn(*row) for row in reversed(rows)]
        selected: list[ConversationTurn] = []
        used = 0
        for turn in reversed(turns):
            size = len(turn.user_text) + len(turn.assistant_text)
            if selected and used + size > self._max_context_chars:
                break
            selected.append(turn)
            used += size
        return list(reversed(selected))

    def append_turn(
        self, session_id: str, user_text: str, assistant_text: str
    ) -> None:
        """追加对话并维护单会话轮数和全局 Session 数上限。"""
        if not session_id or not (user_text.strip() or assistant_text.strip()):
            return
        now = time()
        with self._lock, self._connection:
            self._prune_locked(now)
            self._connection.execute(
                """
                INSERT INTO sessions(session_id, last_active_at)
                VALUES(?, ?)
                ON CONFLICT(session_id) DO UPDATE SET last_active_at=excluded.last_active_at
                """,
                (session_id, now),
            )
            self._connection.execute(
                """
                INSERT INTO conversation_turns(
                    session_id, user_text, assistant_text, created_at
                ) VALUES(?, ?, ?, ?)
                """,
                (session_id, user_text.strip(), assistant_text.strip(), now),
            )
            self._connection.execute(
                """
                DELETE FROM conversation_turns
                WHERE session_id = ? AND id NOT IN (
                    SELECT id FROM conversation_turns
                    WHERE session_id = ? ORDER BY id DESC LIMIT ?
                )
                """,
                (session_id, session_id, self._max_turns),
            )
            self._evict_sessions_locked()

    def clear(self, session_id: str) -> None:
        """删除指定 Session 及其关联对话、运行和事件。"""
        if not session_id:
            return
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM task_runs WHERE session_id = ?", (session_id,)
            )
            self._connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )

    def start_run(self, request_id: str, session_id: str) -> None:
        """记录 Agent Run 开始；request_id 唯一，重复请求不会生成两条记录。"""
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO task_runs(
                    request_id, session_id, status, started_at
                ) VALUES(?, ?, 'running', ?)
                """,
                (request_id, session_id, time()),
            )

    def record_events(self, request_id: str, events: list[dict]) -> None:
        """保存模型选择后的结构化 Skill/Tool 轨迹，便于调试和审计。"""
        if not events:
            return
        with self._lock, self._connection:
            self._connection.executemany(
                """
                INSERT INTO run_events(request_id, sequence, payload_json)
                VALUES(?, ?, ?)
                """,
                [
                    (
                        request_id,
                        index,
                        json.dumps(event, ensure_ascii=False, separators=(",", ":")),
                    )
                    for index, event in enumerate(events, start=1)
                ],
            )

    def finish_run(self, request_id: str, status: str, error: str = "") -> None:
        """写入 Run 最终状态；用于区分完成、取消和失败。"""
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE task_runs
                SET status = ?, finished_at = ?, error = ?
                WHERE request_id = ?
                """,
                (status, time(), error, request_id),
            )

    def close(self) -> None:
        """关闭数据库连接；只应在 Agent Gateway 停机后调用。"""
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions(
                    session_id TEXT PRIMARY KEY,
                    last_active_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_turns(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id)
                        ON DELETE CASCADE,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_runs(
                    request_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS run_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL REFERENCES task_runs(request_id)
                        ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def _prune_locked(self, now: float | None = None) -> None:
        cutoff = (now or time()) - self._ttl_seconds
        expired = self._connection.execute(
            "SELECT session_id FROM sessions WHERE last_active_at < ?", (cutoff,)
        ).fetchall()
        self._delete_sessions_locked([row[0] for row in expired])

    def _evict_sessions_locked(self) -> None:
        evicted = self._connection.execute(
            """
            SELECT session_id FROM sessions
            ORDER BY last_active_at DESC LIMIT -1 OFFSET ?
            """,
            (self._max_sessions,),
        ).fetchall()
        self._delete_sessions_locked([row[0] for row in evicted])

    def _delete_sessions_locked(self, session_ids: list[str]) -> None:
        """删除容量或 TTL 淘汰的 Session，并同步清理运行审计事件。"""
        for session_id in session_ids:
            self._connection.execute(
                "DELETE FROM task_runs WHERE session_id = ?", (session_id,)
            )
            self._connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
