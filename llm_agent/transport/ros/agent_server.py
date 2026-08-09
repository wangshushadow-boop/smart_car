"""统一全模态 Agent ROS 2 Action Server。"""

from __future__ import annotations

from threading import Event, Thread

from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from small_car_interfaces.action import RunAgent

from llm_agent.runtime.runtime import AgentRuntime

from .converters import progress_to_ros, request_from_ros, response_to_ros


class AgentActionServer(Node):
    """把唯一 ROS Action 接口桥接到纯 Python AgentRuntime。"""

    def __init__(
        self,
        runtime: AgentRuntime,
        action_name: str,
        *,
        max_inline_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        super().__init__("llm_agent_server")
        self._runtime = runtime
        self._max_inline_bytes = max_inline_bytes
        self._server = ActionServer(
            self,
            RunAgent,
            action_name,
            execute_callback=self._execute,
            goal_callback=self._accept_goal,
            cancel_callback=self._accept_cancel,
            callback_group=ReentrantCallbackGroup(),
        )
        self.get_logger().info(f"统一全模态 Agent Action：{action_name}")

    def _accept_goal(self, goal_request) -> GoalResponse:
        try:
            request_from_ros(
                goal_request.request, max_inline_bytes=self._max_inline_bytes
            )
        except Exception as error:
            self.get_logger().warning(f"拒绝无效 Agent 请求：{error}")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _accept_cancel(self, _goal_handle) -> CancelResponse:
        return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        request = request_from_ros(
            goal_handle.request.request, max_inline_bytes=self._max_inline_bytes
        )
        cancel_token = Event()
        monitor_done = Event()

        def monitor_cancel() -> None:
            # 模型 HTTP 调用本身可能不能立即中断，但工具和后续节点会观察该令牌。
            while not monitor_done.wait(0.05):
                if goal_handle.is_cancel_requested:
                    cancel_token.set()
                    return

        monitor = Thread(target=monitor_cancel, daemon=True)
        monitor.start()
        try:
            response = self._runtime.run(
                request,
                progress_callback=lambda progress: goal_handle.publish_feedback(
                    RunAgent.Feedback(progress=progress_to_ros(progress))
                ),
                cancel_token=cancel_token,
            )
        finally:
            monitor_done.set()
            monitor.join(timeout=0.2)

        result = RunAgent.Result(response=response_to_ros(response))
        if response.status == "cancelled":
            goal_handle.canceled()
        elif response.status == "failed":
            goal_handle.abort()
        else:
            goal_handle.succeed()
        return result

    def destroy_node(self) -> bool:
        self._server.destroy()
        return super().destroy_node()
