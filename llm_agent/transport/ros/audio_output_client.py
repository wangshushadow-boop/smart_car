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
        """幂等提交播报；播放器忙时短暂重试，但不等待播放结束。"""
        if not self._client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError("树莓派音频播放服务不可用")
        request = PlayAudio.Request()
        request.request_id = request_id
        request.utterance_id = f"{request_id}:final"
        request.mime_type = mime_type
        request.audio = list(audio)
        request.interrupt_current = False
        deadline = monotonic() + self._timeout_seconds
        while monotonic() < deadline:
            future = self._client.call_async(request)
            while not future.done() and monotonic() < deadline:
                sleep(0.01)
            if not future.done():
                break
            response = future.result()
            if response is None:
                raise RuntimeError("音频播放服务没有返回结果")
            if response.accepted:
                return
            if response.error_code != "player_busy":
                detail = response.message or response.error_code or "未知错误"
                raise RuntimeError(f"音频播放服务拒绝：{detail}")
            sleep(0.05)
        raise RuntimeError("音频提交超时：树莓派播放器持续忙碌")
