"""后台 Skill 的生命周期、串行执行和抢占控制。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Callable, Protocol
from uuid import uuid4

from llm_agent.skills import SkillCall

from .contracts import RuntimeRequest, TaskSnapshot, TaskStatus

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskSubmission:
    """DialogueLoop 提交给后台的完整且传输无关的任务输入。"""

    request: RuntimeRequest
    skill_call: SkillCall
    image_urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskRecord:
    """TaskManager 内部持有的可变任务记录。"""

    task_id: str
    submission: TaskSubmission
    cancelled: Event = field(default_factory=Event)
    done: Event = field(default_factory=Event)
    status: TaskStatus = "queued"
    answer: str = ""
    error: str = ""
    state: dict = field(default_factory=dict)

    def snapshot(self) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=self.task_id,
            session_id=self.submission.request.session_id,
            skill_name=self.submission.skill_call.name,
            status=self.status,
            answer=self.answer,
            error=self.error,
        )


class TaskRunner(Protocol):
    """TaskManager 依赖的最小 SkillRunner 契约。"""

    def run(self, record: TaskRecord) -> dict: ...


CompletionListener = Callable[[TaskRecord], None]


class TaskManager:
    """一辆车只运行一个后台任务，新任务以协作取消方式抢占旧任务。"""

    def __init__(self, runner: TaskRunner) -> None:
        self._runner = runner
        self._lock = Lock()
        self._records: dict[str, TaskRecord] = {}
        self._latest_by_session: dict[str, str] = {}
        self._active_task_id = ""
        self._listeners: list[CompletionListener] = []
        # 单 worker 保证底盘和云台不会被两个后台 Skill 同时控制。
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="llm-agent-skill",
        )
        # 语音播报等结束监听可能较慢，不能占用唯一 Skill worker。
        self._notification_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="llm-agent-task-event",
        )
        self._stopping = False

    def add_completion_listener(self, listener: CompletionListener) -> None:
        """注册任务结束通知；监听器不得反向修改任务状态。"""
        self._listeners.append(listener)

    def submit(self, submission: TaskSubmission) -> TaskSnapshot:
        """提交新任务；若旧任务仍占用机器人，则先标记为抢占。"""
        with self._lock:
            if self._stopping:
                raise RuntimeError("TaskManager 正在停止")
            self._preempt_active_locked()
            task_id = f"{submission.request.request_id}-{uuid4().hex[:8]}"
            record = TaskRecord(task_id=task_id, submission=submission)
            self._records[task_id] = record
            self._active_task_id = task_id
            self._latest_by_session[submission.request.session_id] = task_id
            snapshot = record.snapshot()
        self._executor.submit(self._run, task_id)
        return snapshot

    def cancel_active(self) -> TaskSnapshot | None:
        """取消当前机器人任务；不存在活动任务时返回 None。"""
        with self._lock:
            record = self._active_locked()
            if record is None:
                return None
            record.status = "cancelled"
            record.cancelled.set()
            self._active_task_id = ""
            return record.snapshot()

    def latest(self, session_id: str) -> TaskSnapshot | None:
        """返回该会话最后一次任务的稳定快照。"""
        with self._lock:
            task_id = self._latest_by_session.get(session_id)
            record = self._records.get(task_id or "")
            return record.snapshot() if record else None

    def wait(self, task_id: str, timeout: float = 5.0) -> TaskSnapshot:
        """等待指定任务结束；主要供状态接口和确定性测试使用。"""
        with self._lock:
            record = self._records.get(task_id)
        if record is None:
            raise KeyError(f"task not found: {task_id}")
        if not record.done.wait(timeout):
            raise TimeoutError(f"等待任务超时：{task_id}")
        with self._lock:
            return record.snapshot()

    def result_state(self, task_id: str) -> dict:
        """返回任务结果副本，防止调用方修改内部记录。"""
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise KeyError(f"task not found: {task_id}")
            return dict(record.state)

    def stop(self) -> None:
        """拒绝新任务并取消当前任务。"""
        with self._lock:
            self._stopping = True
            record = self._active_locked()
            if record:
                record.status = "cancelled"
                record.cancelled.set()
            self._active_task_id = ""
            self._listeners.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._notification_executor.shutdown(wait=False, cancel_futures=True)
        stop_runner = getattr(self._runner, "stop", None)
        if callable(stop_runner):
            stop_runner()

    def _run(self, task_id: str) -> None:
        with self._lock:
            record = self._records[task_id]
            if record.status != "queued":
                record.done.set()
                return
            record.status = "running"
        try:
            state = self._runner.run(record)
        except Exception as error:  # 后台线程的异常必须转换为可观察任务状态。
            state = {"answer": "任务未能完成。", "error": str(error)}

        with self._lock:
            record.state = state
            record.answer = str(state.get("answer", "")).strip()
            record.error = str(state.get("error", "")).strip()
            if record.status not in {"cancelled", "preempted"}:
                record.status = "failed" if record.error else "completed"
            if self._active_task_id == task_id:
                self._active_task_id = ""
            should_notify = (
                not self._stopping and record.status in {"completed", "failed"}
            )
            record.done.set()
        if should_notify:
            self._notification_executor.submit(self._notify, record)

    def _notify(self, record: TaskRecord) -> None:
        for listener in tuple(self._listeners):
            try:
                listener(record)
            except Exception:
                _LOGGER.exception("后台任务结束监听器执行失败：%s", record.task_id)

    def _preempt_active_locked(self) -> None:
        record = self._active_locked()
        if record is None:
            return
        record.status = "preempted"
        record.cancelled.set()
        self._active_task_id = ""

    def _active_locked(self) -> TaskRecord | None:
        record = self._records.get(self._active_task_id)
        if record and record.status in {"queued", "running"}:
            return record
        return None
