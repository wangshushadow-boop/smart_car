"""Agent Server 访问树莓派 Robot Tool Gateway 的唯一 ROS 客户端。"""

from __future__ import annotations

import json
from threading import Event, Lock
from time import monotonic, sleep

from rclpy.action import ActionClient
from rclpy.node import Node
from small_car_interfaces.action import ExecuteRobotTool


class RosRobotToolClient(Node):
    """把同步 Tool 调用适配为异步 ROS Action，并集中处理取消与超时。"""

    def __init__(self, action_name: str) -> None:
        super().__init__("llm_agent_robot_tool_client")
        self._client = ActionClient(self, ExecuteRobotTool, action_name)
        self._step_lock = Lock()
        self._steps: dict[str, int] = {}
        self._observations: dict[str, list[bytes]] = {}

    def execute(
        self,
        tool_name: str,
        arguments: dict,
        *,
        task_id: str,
        cancelled: Event,
        timeout_seconds: float = 20.0,
        request_observation: bool = False,
    ) -> dict:
        if cancelled.is_set():
            raise RuntimeError("request cancelled")
        if not self._client.wait_for_server(timeout_sec=1.0):
            raise RuntimeError("Robot Tool Gateway 不可用")
        with self._step_lock:
            if len(self._steps) > 4096:
                self._steps.clear()
            step_id = self._steps.get(task_id, 0) + 1
            self._steps[task_id] = step_id

        goal = ExecuteRobotTool.Goal()
        goal.task_id = task_id
        goal.step_id = step_id
        goal.tool_name = tool_name
        goal.arguments_json = json.dumps(
            arguments, ensure_ascii=False, separators=(",", ":")
        )
        goal.request_observation = request_observation

        send_future = self._client.send_goal_async(goal)
        self._wait_future(send_future, cancelled, 2.0, "工具请求提交超时")
        handle = send_future.result()
        if handle is None or not handle.accepted:
            raise RuntimeError("Robot Tool Gateway 拒绝了请求")

        result_future = handle.get_result_async()
        deadline = monotonic() + timeout_seconds
        while not result_future.done():
            if cancelled.is_set() or monotonic() >= deadline:
                handle.cancel_goal_async()
                reason = "request cancelled" if cancelled.is_set() else "工具执行超时"
                raise RuntimeError(reason)
            sleep(0.02)
        wrapped = result_future.result()
        result = wrapped.result
        if result is None or not result.success:
            detail = result.message if result is not None else "工具没有返回结果"
            raise RuntimeError(detail)
        observations = [bytes(item.data) for item in result.observations if item.data]
        if observations:
            self._observations[task_id] = observations
        payload = json.loads(result.result_json or "{}")
        if not isinstance(payload, dict):
            payload = {}
        return {
            "schema": "small_car.tool_result.v1",
            "executed": True,
            "tool_name": tool_name,
            "step_id": step_id,
            "message": result.message,
            "observation_count": len(observations),
            **payload,
        }

    def take_observations(self, task_id: str) -> list[bytes]:
        """为后续动态 Skill 取出最近一次工具动作后的图片。"""
        return self._observations.pop(task_id, [])

    @staticmethod
    def _wait_future(future, cancelled: Event, timeout: float, message: str) -> None:
        deadline = monotonic() + timeout
        while not future.done():
            if cancelled.is_set():
                raise RuntimeError("request cancelled")
            if monotonic() >= deadline:
                raise RuntimeError(message)
            sleep(0.01)
