"""统一全模态 Agent ROS 2 Action Server 及其消息边界转换。"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Event, Thread
from typing import Iterator

import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from small_car_interfaces.action import RunAgent
from small_car_interfaces.msg import AgentContent as RosAgentContent
from small_car_interfaces.msg import AgentProgress as RosAgentProgress
from small_car_interfaces.msg import AgentResponse as RosAgentResponse

from llm_agent.runtime.contracts import (
    ContentPart,
    ContentType,
    RuntimeProgress,
    RuntimeRequest,
    RuntimeResponse,
)


_ROS_TO_CONTENT = {
    RosAgentContent.TEXT: ContentType.TEXT,
    RosAgentContent.AUDIO: ContentType.AUDIO,
    RosAgentContent.IMAGE: ContentType.IMAGE,
    RosAgentContent.VIDEO: ContentType.VIDEO,
    RosAgentContent.JSON: ContentType.JSON,
}
_CONTENT_TO_ROS = {value: key for key, value in _ROS_TO_CONTENT.items()}


def _load_action_name(key: str) -> str:
    package_share = Path(get_package_share_directory("small_car_interfaces"))
    with (package_share / "config" / "interfaces.yaml").open(encoding="utf-8") as file:
        contract = yaml.safe_load(file)
    actions = contract.get("actions", {}) if isinstance(contract, dict) else {}
    name = actions.get(key, {}).get("name")
    if not isinstance(name, str) or not name.startswith("/"):
        raise RuntimeError(f"统一 Agent Action 契约缺少 {key}")
    return name


def load_agent_action_name() -> str:
    return _load_action_name("agent_run")


def load_robot_tool_action_name() -> str:
    return _load_action_name("robot_tool_execute")


def request_from_ros(message, *, max_inline_bytes: int) -> RuntimeRequest:
    inline_size = sum(len(part.data) for part in message.inputs)
    if inline_size > max_inline_bytes:
        raise ValueError(f"内联媒体总大小超过限制：{inline_size} > {max_inline_bytes}")
    created_seconds = message.created_at.sec + message.created_at.nanosec / 1e9
    created_at = (
        datetime.fromtimestamp(created_seconds, timezone.utc)
        if created_seconds > 0
        else datetime.now(timezone.utc)
    )
    return RuntimeRequest(
        request_id=message.request_id,
        session_id=message.session_id,
        source=message.source or "ros",
        created_at=created_at,
        inputs=[_content_from_ros(part) for part in message.inputs],
        response_modalities=[ContentType(value) for value in message.response_modalities],
        allow_tools=message.allow_tools,
        stream_progress=message.stream_progress,
        metadata=_load_json_object(message.metadata_json),
    )


def response_to_ros(response: RuntimeResponse) -> RosAgentResponse:
    message = RosAgentResponse()
    message.request_id = response.request_id
    message.session_id = response.session_id
    message.status = response.status
    message.outputs = [_content_to_ros(part) for part in response.outputs]
    message.generation_provider = response.generation_provider
    message.speech_provider = response.speech_provider
    message.error_code = response.error_code
    message.error_message = response.error_message
    message.metadata_json = json.dumps(response.metadata, ensure_ascii=False)
    return message


def progress_to_ros(progress: RuntimeProgress) -> RosAgentProgress:
    message = RosAgentProgress()
    message.request_id = progress.request_id
    message.stage = progress.stage
    message.percent = progress.percent
    message.message = progress.message
    message.partial_outputs = [_content_to_ros(part) for part in progress.partial_outputs]
    return message


def _content_from_ros(message: RosAgentContent) -> ContentPart:
    content_type = _ROS_TO_CONTENT.get(message.content_type)
    if content_type is None:
        raise ValueError(f"未知 Agent 内容类型：{message.content_type}")
    return ContentPart(
        type=content_type,
        name=message.name,
        mime_type=message.mime_type,
        text=message.text,
        data=bytes(message.data),
        uri=message.uri,
        topic=message.topic,
        metadata=_load_json_object(message.metadata_json),
    )


def _content_to_ros(part: ContentPart) -> RosAgentContent:
    message = RosAgentContent()
    message.content_type = _CONTENT_TO_ROS[part.type]
    message.name = part.name
    message.mime_type = part.mime_type
    message.text = part.text
    message.data = list(part.data)
    message.uri = part.uri
    message.topic = part.topic
    message.metadata_json = json.dumps(part.metadata, ensure_ascii=False)
    return message


def _load_json_object(value: str) -> dict:
    if not value:
        return {}
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("metadata_json 必须是 JSON 对象")
    return payload


@lru_cache(maxsize=1)
def _trace_library():
    for candidate in [
        ctypes.util.find_library("tracetools"),
        "/opt/ros/kilted/lib/libtracetools.so",
    ]:
        if not candidate:
            continue
        if Path(candidate).is_absolute() and not Path(candidate).is_file():
            continue
        try:
            library = ctypes.CDLL(candidate)
            library.ros_trace_rclcpp_callback_register
            library.ros_trace_callback_start
            library.ros_trace_callback_end
            return library
        except (AttributeError, OSError):
            continue
    return None


def _callback_pointer(callback) -> ctypes.c_void_p:
    instance = getattr(callback, "__self__", None)
    function = getattr(callback, "__func__", callback)
    identity = id(function)
    if instance is not None:
        identity ^= id(instance)
    return ctypes.c_void_p(identity or 1)


@contextmanager
def ros_trace_scope(callback, name: str) -> Iterator[None]:
    library = _trace_library()
    if library is None:
        yield
        return
    pointer = _callback_pointer(callback)
    trace_name = name.encode("utf-8") if isinstance(library, ctypes.CDLL) else name
    try:
        library.ros_trace_rclcpp_callback_register(pointer, trace_name)
        library.ros_trace_callback_start(pointer, False)
    except Exception:
        yield
        return
    try:
        yield
    finally:
        library.ros_trace_callback_end(pointer)


class AgentActionServer(Node):
    """把唯一 ROS Action 接口桥接到纯 Python AgentGateway。"""

    def __init__(
        self,
        gateway,
        action_name: str,
        *,
        max_inline_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        super().__init__("llm_agent_server")
        self._gateway = gateway
        self._max_inline_bytes = max_inline_bytes
        # 使用可重入回调组：feedback publish 与 execute_callback 不会互相阻塞。
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
        """先做一次轻量校验，把超容量的 Goal 直接拒掉，避免 Runtime 被拖垮。"""
        with ros_trace_scope(self._accept_goal, "AgentActionServer._accept_goal"):
            return self._accept_goal_traced(goal_request)

    def _accept_goal_traced(self, goal_request) -> GoalResponse:
        try:
            request_from_ros(
                goal_request.request, max_inline_bytes=self._max_inline_bytes
            )
        except Exception as error:
            self.get_logger().warning(f"拒绝无效 Agent 请求：{error}")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _accept_cancel(self, _goal_handle) -> CancelResponse:
        """始终接受取消请求；具体的中断由 Runtime 内部令牌驱动。"""
        with ros_trace_scope(self._accept_cancel, "AgentActionServer._accept_cancel"):
            return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        """单 Goal 完整执行：转换 → Runtime → 反馈 → 取消监听。"""
        with ros_trace_scope(self._execute, "AgentActionServer._execute"):
            return self._execute_traced(goal_handle)

    def _execute_traced(self, goal_handle):
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

        # 守护线程：Runtime 退出时一并结束，无需手动清理。
        monitor = Thread(target=monitor_cancel, daemon=True)
        monitor.start()
        try:
            response = self._gateway.run(
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
        # 根据 Runtime 状态决定 ROS Action 的最终结果分类。
        if response.status == "cancelled":
            goal_handle.canceled()
        elif response.status == "failed":
            goal_handle.abort()
        else:
            goal_handle.succeed()
        return result

    def destroy_node(self) -> bool:
        """Node 销毁前先关闭 ActionServer，避免 ROS 资源泄漏。"""
        self._server.destroy()
        return super().destroy_node()
