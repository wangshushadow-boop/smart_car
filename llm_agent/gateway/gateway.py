"""所有调用端进入 llm_agent 的统一 Gateway。

Gateway 不理解模型、Skill 或 ROS 业务，只负责请求幂等、同 Session 串行、
生命周期和取消令牌透传。ROS Action、Web 或 CLI Adapter 均应依赖本接口。
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Event, Lock

from llm_agent.runtime import AgentRuntime, RuntimeRequest, RuntimeResponse


class AgentGateway:
    """为纯 Runtime 增加传输无关的并发与幂等控制。"""

    def __init__(self, runtime: AgentRuntime, *, cache_size: int = 256) -> None:
        self._runtime = runtime
        self._cache_size = cache_size
        self._guard = Lock()
        self._session_locks: dict[str, Lock] = {}
        self._responses: OrderedDict[str, RuntimeResponse] = OrderedDict()

    def run(
        self,
        request: RuntimeRequest,
        progress_callback=None,
        cancel_token: Event | None = None,
    ) -> RuntimeResponse:
        """相同 request_id 返回缓存结果；同一 Session 的请求严格串行。"""
        with self._guard:
            cached = self._responses.get(request.request_id)
            if cached is not None:
                self._responses.move_to_end(request.request_id)
                return cached
            key = request.session_id or f"source:{request.source}"
            session_lock = self._session_locks.setdefault(key, Lock())
        with session_lock:
            # 等锁期间同 request_id 可能已由前一个请求完成，进入 Runtime 前再查一次。
            with self._guard:
                cached = self._responses.get(request.request_id)
                if cached is not None:
                    self._responses.move_to_end(request.request_id)
                    return cached
            response = self._runtime.run(
                request,
                progress_callback=progress_callback,
                cancel_token=cancel_token,
            )
        with self._guard:
            self._responses[request.request_id] = response
            self._responses.move_to_end(request.request_id)
            while len(self._responses) > self._cache_size:
                self._responses.popitem(last=False)
        return response

    def clear_session(self, session_id: str) -> None:
        """清除一个会话，不影响其他入口和任务。"""
        self._runtime.clear_conversation(session_id)

    def stop(self) -> None:
        """停止接收新任务并释放 Runtime 资源。"""
        self._runtime.stop()
