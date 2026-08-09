"""ROS 全模态消息与 Runtime 领域对象之间的双向转换。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

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


def request_from_ros(message, *, max_inline_bytes: int) -> RuntimeRequest:
    """校验 ROS Goal，并转换成不依赖 ROS 的 RuntimeRequest。"""
    inline_size = sum(len(part.data) for part in message.inputs)
    if inline_size > max_inline_bytes:
        raise ValueError(
            f"内联媒体总大小超过限制：{inline_size} > {max_inline_bytes}"
        )
    created_seconds = message.created_at.sec + message.created_at.nanosec / 1e9
    created_at = (
        datetime.fromtimestamp(created_seconds, timezone.utc)
        if created_seconds > 0
        else datetime.now(timezone.utc)
    )
    inputs = [_content_from_ros(part) for part in message.inputs]
    return RuntimeRequest(
        request_id=message.request_id,
        session_id=message.session_id,
        source=message.source or "ros",
        created_at=created_at,
        inputs=inputs,
        response_modalities=[ContentType(value) for value in message.response_modalities],
        allow_tools=message.allow_tools,
        stream_progress=message.stream_progress,
        metadata=_load_json_object(message.metadata_json),
    )


def response_to_ros(response: RuntimeResponse) -> RosAgentResponse:
    """把 RuntimeResponse 转为 Action Result 中的 ROS 消息。"""
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
    """把 Runtime 进度转换为 Action Feedback。"""
    message = RosAgentProgress()
    message.request_id = progress.request_id
    message.stage = progress.stage
    message.percent = progress.percent
    message.message = progress.message
    message.partial_outputs = [
        _content_to_ros(part) for part in progress.partial_outputs
    ]
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
