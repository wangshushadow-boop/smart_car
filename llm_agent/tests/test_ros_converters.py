from __future__ import annotations

import unittest

from small_car_interfaces.msg import AgentContent, AgentRequest

from llm_agent.runtime import ContentPart, ContentType, RuntimeResponse
from llm_agent.transport.ros.converters import request_from_ros, response_to_ros


class RosConvertersTest(unittest.TestCase):
    def test_converts_all_input_modalities(self) -> None:
        request = AgentRequest()
        request.request_id = "request-1"
        request.session_id = "session-1"
        request.source = "test"
        request.inputs = [
            self._content(AgentContent.TEXT, "text/plain", text="看到了什么"),
            self._content(AgentContent.AUDIO, "audio/wav", data=b"wav"),
            self._content(AgentContent.IMAGE, "image/jpeg", data=b"jpg"),
            self._content(AgentContent.VIDEO, "video/mp4", data=b"mp4"),
        ]
        request.response_modalities = ["text", "audio"]
        request.allow_tools = True
        converted = request_from_ros(request, max_inline_bytes=1024)
        self.assertEqual(converted.request_id, "request-1")
        self.assertEqual(
            [part.type for part in converted.inputs],
            [ContentType.TEXT, ContentType.AUDIO, ContentType.IMAGE, ContentType.VIDEO],
        )

    def test_rejects_oversized_inline_media(self) -> None:
        request = AgentRequest()
        request.request_id = "large"
        request.source = "test"
        request.inputs = [
            self._content(AgentContent.IMAGE, "image/jpeg", data=b"12345")
        ]
        request.response_modalities = ["text"]
        with self.assertRaisesRegex(ValueError, "超过限制"):
            request_from_ros(request, max_inline_bytes=4)

    def test_converts_multimodal_response(self) -> None:
        response = RuntimeResponse(
            request_id="request-1",
            status="completed",
            outputs=[
                ContentPart(type=ContentType.TEXT, text="回答"),
                ContentPart(type=ContentType.AUDIO, mime_type="audio/wav", data=b"wav"),
            ],
        )
        message = response_to_ros(response)
        self.assertEqual(message.outputs[0].content_type, AgentContent.TEXT)
        self.assertEqual(bytes(message.outputs[1].data), b"wav")

    @staticmethod
    def _content(
        content_type: int, mime_type: str, *, text: str = "", data: bytes = b""
    ) -> AgentContent:
        content = AgentContent()
        content.content_type = content_type
        content.mime_type = mime_type
        content.text = text
        content.data = list(data)
        return content


if __name__ == "__main__":
    unittest.main()
