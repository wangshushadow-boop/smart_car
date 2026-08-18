"""统一全模态 Agent ROS 2 Service 及其消息边界转换。"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from small_car_interfaces.msg import AgentContent as RosAgentContent
from small_car_interfaces.msg import AgentResponse as RosAgentResponse
from small_car_interfaces.srv import RunAgent

from llm_agent.runtime.contracts import (
    ContentPart,
    ContentType,
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


def _load_interface_name(section: str, key: str) -> str:
    package_share = Path(get_package_share_directory("small_car_interfaces"))
    with (package_share / "config" / "interfaces.yaml").open(encoding="utf-8") as file:
        contract = yaml.safe_load(file)
    entries = contract.get(section, {}) if isinstance(contract, dict) else {}
    name = entries.get(key, {}).get("name")
    if not isinstance(name, str) or not name.startswith("/"):
        raise RuntimeError(f"统一 Agent 接口契约缺少 {section}.{key}")
    return name


def load_agent_service_name() -> str:
    return _load_interface_name("services", "agent_run")


def load_robot_tool_action_name() -> str:
    return _load_interface_name("actions", "robot_tool_execute")


def load_audio_service_name() -> str:
    """从统一接口契约读取树莓派音频入队 Service。"""
    return _load_interface_name("services", "audio_enqueue")


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
        stream_progress=False,
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


class AgentServiceServer(Node):
    """把短 DialogueLoop 暴露为唯一 ROS Service。"""

    def __init__(
        self,
        gateway,
        service_name: str,
        *,
        max_inline_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        super().__init__("llm_agent_server")
        self._gateway = gateway
        self._max_inline_bytes = max_inline_bytes
        # 不同 Session 可以并发进入 Gateway；同 Session 仍由 Gateway 串行。
        self._server = self.create_service(
            RunAgent,
            service_name,
            self._handle,
            callback_group=ReentrantCallbackGroup(),
        )
        self.get_logger().info(f"统一全模态 Agent Service：{service_name}")

    def _handle(self, service_request, service_response):
        """完成一次短对话；后台 Skill 的生命周期不占用 Service。"""
        with ros_trace_scope(self._handle, "AgentServiceServer._handle"):
            return self._handle_traced(service_request, service_response)

    def _handle_traced(self, service_request, service_response):
        try:
            request = request_from_ros(
                service_request.request,
                max_inline_bytes=self._max_inline_bytes,
            )
            response = self._gateway.run(request)
        except Exception as error:
            request_id = getattr(service_request.request, "request_id", "")
            response = RuntimeResponse(
                request_id=request_id or "invalid-request",
                status="failed",
                error_code="invalid_request",
                error_message=str(error),
            )
            self.get_logger().warning(f"Agent Service 请求失败：{error}")
        service_response.response = response_to_ros(response)
        return service_response

    def destroy_node(self) -> bool:
        """Node 销毁前先关闭 Service，避免 ROS 资源泄漏。"""
        self.destroy_service(self._server)
        return super().destroy_node()
