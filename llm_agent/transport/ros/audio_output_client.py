"""Agent Server 到树莓派后台播放器的最小 ROS Service 适配器。"""

from __future__ import annotations

from time import monotonic, sleep

from rclpy.node import Node
from small_car_interfaces.srv import PlayAudio


class RosAudioOutputClient(Node):
    """提交最终 WAV 并等待“播放器已接收”，不等待整段音频播放结束。"""

    def __init__(self, service_name: str, timeout_seconds: float = 5.0) -> None:
        super().__init__("llm_agent_audio_output_client")
        self._client = self.create_client(PlayAudio, service_name)
        self._timeout_seconds = timeout_seconds

    def enqueue(self, *, request_id: str, audio: bytes, mime_type: str) -> None:
        """把一次最终播报幂等地提交给树莓派播放器。"""
        if not self._client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError("树莓派音频播放服务不可用")
        request = PlayAudio.Request()
        request.request_id = request_id
        request.utterance_id = f"{request_id}:final"
        request.mime_type = mime_type
        request.audio = list(audio)
        request.interrupt_current = False
        future = self._client.call_async(request)
        deadline = monotonic() + self._timeout_seconds
        while not future.done():
            if monotonic() >= deadline:
                raise RuntimeError("音频提交超时")
            sleep(0.01)
        response = future.result()
        if response is None:
            raise RuntimeError("音频播放服务没有返回结果")
        if not response.accepted:
            detail = response.message or response.error_code or "未知错误"
            raise RuntimeError(f"音频播放服务拒绝：{detail}")
