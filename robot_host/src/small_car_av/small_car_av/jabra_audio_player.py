"""订阅模型返回的 PCM 音频并通过树莓派 ALSA 设备播放。"""

import subprocess

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from small_car_interfaces.msg import AudioFrame


class JabraAudioPlayer(Node):
    def __init__(self) -> None:
        super().__init__("small_car_jabra_audio_player")
        self.declare_parameter("alsa_device", "plughw:CARD=USB,DEV=0")
        self._device = str(self.get_parameter("alsa_device").value)
        self._playback = None
        self._format = None
        audio_output_qos = QoSProfile(depth=100)
        audio_output_qos.reliability = ReliabilityPolicy.RELIABLE
        self.create_subscription(
            AudioFrame, "/car/audio/output", self._on_audio, audio_output_qos
        )
        self.get_logger().info(f"等待模型语音，将通过 ALSA {self._device} 播放")

    def _start(self, sample_rate: int, channels: int) -> None:
        self._stop()
        self._format = (sample_rate, channels)
        self._playback = subprocess.Popen(
            [
                "aplay", "--quiet", "--device", self._device,
                "--format", "S16_LE", "--rate", str(sample_rate),
                "--channels", str(channels), "--file-type", "raw",
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _on_audio(self, msg: AudioFrame) -> None:
        if msg.encoding.lower() != "pcm_s16le" or not msg.data:
            return
        audio_format = (msg.sample_rate, msg.channels)
        if self._playback is None or self._playback.poll() is not None or self._format != audio_format:
            self._start(*audio_format)
        try:
            self._playback.stdin.write(bytes(msg.data))
            self._playback.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            self.get_logger().error(f"ALSA 播放失败：{error}")
            self._stop()

    def _stop(self) -> None:
        if self._playback is None:
            return
        if self._playback.poll() is None:
            self._playback.terminate()
            try:
                self._playback.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._playback.kill()
        self._playback = None

    def destroy_node(self) -> bool:
        self._stop()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = JabraAudioPlayer()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
