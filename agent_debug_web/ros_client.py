"""Web Debug 使用的 ROS Action Client；本模块不依赖 llm_agent。"""

from __future__ import annotations

import base64
import json
from threading import Event, Thread
from uuid import uuid4

import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from small_car_interfaces.action import RunAgent
from small_car_interfaces.msg import AgentContent, AgentRequest

from .interface_contract import load_agent_action_name


_CONTENT_TYPES = {
    "text": AgentContent.TEXT,
    "audio": AgentContent.AUDIO,
    "image": AgentContent.IMAGE,
    "video": AgentContent.VIDEO,
    "json": AgentContent.JSON,
}


class RosAgentClient:
    """在后台执行 ROS Executor，并向 HTTP 线程提供同步请求方法。"""

    def __init__(self) -> None:
        rclpy.init()
        self._node = Node("agent_debug_web")
        self._client = ActionClient(
            self._node, RunAgent, load_agent_action_name()
        )
        self._executor = MultiThreadedExecutor(num_threads=2)
        self._executor.add_node(self._node)
        self._thread = Thread(target=self._executor.spin, daemon=True)
        self._thread.start()

    def submit(self, payload: dict, timeout_seconds: float = 180) -> dict:
        """把 Web JSON 转成统一 Goal，并等待对应的 Action Result。"""
        if not self._client.wait_for_server(timeout_sec=5):
            raise RuntimeError("Agent Action Server 不可用")
        goal = RunAgent.Goal()
        goal.request = self._build_request(payload)
        goal_future = self._client.send_goal_async(goal)
        goal_handle = self._wait_future(goal_future, timeout_seconds)
        if not goal_handle.accepted:
            raise ValueError("Agent 拒绝了请求，请检查输入格式或媒体大小")
        result_future = goal_handle.get_result_async()
        wrapped_result = self._wait_future(result_future, timeout_seconds)
        return self._response_to_json(wrapped_result.result.response)

    def stop(self) -> None:
        self._executor.shutdown()
        self._node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        self._thread.join(timeout=2)

    def _build_request(self, payload: dict) -> AgentRequest:
        inputs = payload.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            raise ValueError("inputs 必须是非空数组")
        request = AgentRequest()
        request.request_id = uuid4().hex
        request.session_id = str(payload.get("session_id", "web-debug"))
        request.source = "web_debug"
        request.created_at = self._node.get_clock().now().to_msg()
        request.inputs = [self._content_from_json(part) for part in inputs]
        modalities = payload.get("response_modalities", ["text"])
        if not isinstance(modalities, list) or not modalities:
            raise ValueError("response_modalities 必须是非空数组")
        request.response_modalities = [str(value) for value in modalities]
        request.allow_tools = bool(payload.get("allow_tools", True))
        request.stream_progress = True
        request.metadata_json = json.dumps(
            payload.get("metadata", {}), ensure_ascii=False
        )
        return request

    @staticmethod
    def _content_from_json(payload: dict) -> AgentContent:
        if not isinstance(payload, dict):
            raise ValueError("每个输入内容必须是对象")
        kind = payload.get("type")
        if kind not in _CONTENT_TYPES:
            raise ValueError(f"不支持的内容类型：{kind}")
        message = AgentContent()
        message.content_type = _CONTENT_TYPES[kind]
        message.name = str(payload.get("name", ""))
        message.mime_type = str(payload.get("mime_type", ""))
        message.text = str(payload.get("text", ""))
        encoded = payload.get("data_base64", "")
        if encoded:
            try:
                message.data = list(base64.b64decode(encoded, validate=True))
            except ValueError as error:
                raise ValueError("data_base64 不是有效 Base64") from error
        message.uri = str(payload.get("uri", ""))
        message.topic = str(payload.get("topic", ""))
        message.metadata_json = json.dumps(
            payload.get("metadata", {}), ensure_ascii=False
        )
        return message

    @staticmethod
    def _response_to_json(response) -> dict:
        outputs = []
        type_names = {value: key for key, value in _CONTENT_TYPES.items()}
        for part in response.outputs:
            outputs.append(
                {
                    "type": type_names.get(part.content_type, "unknown"),
                    "name": part.name,
                    "mime_type": part.mime_type,
                    "text": part.text,
                    "data_base64": (
                        base64.b64encode(bytes(part.data)).decode("ascii")
                        if part.data
                        else ""
                    ),
                    "uri": part.uri,
                    "metadata": json.loads(part.metadata_json or "{}"),
                }
            )
        return {
            "request_id": response.request_id,
            "session_id": response.session_id,
            "status": response.status,
            "outputs": outputs,
            "generation_provider": response.generation_provider,
            "speech_provider": response.speech_provider,
            "error_code": response.error_code,
            "error_message": response.error_message,
            "metadata": json.loads(response.metadata_json or "{}"),
        }

    @staticmethod
    def _wait_future(future, timeout_seconds: float):
        completed = Event()
        future.add_done_callback(lambda _future: completed.set())
        if not completed.wait(timeout_seconds):
            raise TimeoutError("等待 Agent 响应超时")
        error = future.exception()
        if error:
            raise error
        return future.result()
