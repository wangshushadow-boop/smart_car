"""直接订阅树莓派音视频 topic，并在语音结束时触发 Agent。"""
from __future__ import annotations

import audioop
import base64
import io
import time
import wave
from array import array
from collections import deque
from queue import Queue
from threading import Event, Thread

from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage
from small_car_interfaces.msg import AudioFrame
from std_msgs.msg import Empty

from llm_agent.agent.events import AgentEvent, SpeechFinished
from .interface_contract import load_topics
from .playback_echo import PlaybackEchoSuppressor


def _stamp_ns(stamp) -> int:
    return stamp.sec * 1_000_000_000 + stamp.nanosec


class RosPerceptionInput(Node):
    """WSL Agent 输入节点：缓存画面、检测语句结束、后台执行 Agent。"""

    def __init__(self, handler) -> None:
        super().__init__("llm_agent_perception_input")
        self._handler = handler
        topics = load_topics()
        audio_output_qos = QoSProfile(depth=100)
        audio_output_qos.reliability = ReliabilityPolicy.RELIABLE
        self._audio_output = self.create_publisher(
            AudioFrame, topics["audio_output"], audio_output_qos
        )
        # Playback no longer disables capture.  The reference canceller removes
        # the robot's own speaker signal, then VAD can still detect a person
        # speaking over TTS (barge-in).
        self._playback_active = Event()
        self._playback_cancel = Event()
        self._echo_suppressor = PlaybackEchoSuppressor()
        playback_stop_qos = QoSProfile(depth=1)
        playback_stop_qos.reliability = ReliabilityPolicy.RELIABLE
        self._audio_playback_stop = self.create_publisher(
            Empty, topics["audio_playback_stop"], playback_stop_qos
        )
        self._image: tuple[int, bytes] | None = None
        self._frames = deque(maxlen=750)  # 最多约 15 秒，20 ms/帧。
        self._speech_frames = []
        self._speech_ns = 0
        self._silence_ns = 0
        self.declare_parameter("vad_energy_threshold", 500)
        self.declare_parameter("vad_min_speech_ms", 300)
        self.declare_parameter("vad_silence_ms", 600)
        self.declare_parameter("barge_in_energy_threshold", 700)
        self._events: Queue[AgentEvent | None] = Queue(maxsize=4)
        self._stopping = Event()
        self._worker = Thread(target=self._run, daemon=True)
        self._worker.start()
        self.create_subscription(
            CompressedImage,
            topics["camera_image_compressed"],
            self._on_image,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            AudioFrame, topics["audio_input"], self._on_audio, qos_profile_sensor_data
        )

    def _on_image(self, msg: CompressedImage) -> None:
        self._image = (_stamp_ns(msg.header.stamp), bytes(msg.data))

    def _on_audio(self, msg: AudioFrame) -> None:
        data = bytes(msg.data)
        if (msg.encoding.lower() != "pcm_s16le" or not data or msg.sample_rate <= 0 or
                msg.channels != 1 or msg.frame_samples * 2 != len(data)):
            return
        cleaned_data, correlation, residual_ratio = self._echo_suppressor.suppress(
            data, msg.sample_rate, msg.channels
        )
        speech = audioop.rms(cleaned_data, 2) >= int(self.get_parameter("vad_energy_threshold").value)
        external_speech = (
            audioop.rms(cleaned_data, 2) >= int(self.get_parameter("barge_in_energy_threshold").value)
            and self._echo_suppressor.is_external_speech(correlation, residual_ratio)
        )
        if self._playback_active.is_set():
            if external_speech:
                # Stop both producers: no more frames are sent from this Agent,
                # and the Pi discards frames that have already crossed ROS.
                self._playback_cancel.set()
                self._playback_active.clear()
                self._audio_playback_stop.publish(Empty())
                self.get_logger().info("检测到外部语音，已打断当前播报")
            else:
                # During playback only an independent voice may enter the VAD
                # pipeline.  This prevents a residual speaker syllable from
                # becoming a follow-up request when cancellation is imperfect.
                return
        elif correlation >= 0.60 and residual_ratio < 0.45:
            # The last speaker samples may still reach the microphone briefly
            # after playback has ended; do not turn that tail into a new request.
            return
        frame = (msg, cleaned_data, _stamp_ns(msg.header.stamp),
                 msg.frame_samples * 1_000_000_000 // msg.sample_rate)
        self._frames.append(frame)
        if not self._speech_frames and not speech:
            return
        # Persist the echo-suppressed waveform so the model receives the user's
        # voice rather than its own previous answer.
        self._speech_frames.append((msg, cleaned_data, frame[2], frame[3]))
        if speech:
            self._speech_ns += frame[3]
            self._silence_ns = 0
        else:
            self._silence_ns += frame[3]
        if self._silence_ns >= int(self.get_parameter("vad_silence_ms").value) * 1_000_000:
            self._finish_speech()

    def _finish_speech(self) -> None:
        frames, self._speech_frames = self._speech_frames, []
        speech_ns, self._speech_ns = self._speech_ns, 0
        self._silence_ns = 0
        if not frames or speech_ns < int(self.get_parameter("vad_min_speech_ms").value) * 1_000_000:
            return
        first_msg = frames[0][0]
        wav = io.BytesIO()
        with wave.open(wav, "wb") as output:
            output.setnchannels(first_msg.channels)
            output.setsampwidth(2)
            output.setframerate(first_msg.sample_rate)
            output.writeframes(b"".join(frame[1] for frame in frames))
        image_url = None
        if self._image:
            image_url = "data:image/jpeg;base64," + base64.b64encode(self._image[1]).decode("ascii")
        event = SpeechFinished(
            speech_wav=wav.getvalue(),
            perception={"image_data_url": image_url},
        )
        if self._events.full():
            self.get_logger().warning("Agent 忙碌，丢弃语音事件")
        else:
            self._events.put_nowait(event)
            self.get_logger().info("语音结束，直接触发本地 Agent")

    def publish_wav(self, wav_data: bytes) -> None:
        """Send PCM at its real playback rate while capture remains active."""
        with wave.open(io.BytesIO(wav_data), "rb") as source:
            if source.getsampwidth() != 2:
                raise ValueError("模型语音不是 16-bit PCM WAV")
            sample_rate = source.getframerate()
            channels = source.getnchannels()
            frame_samples = max(1, sample_rate // 50)
            # aplay starts consuming as soon as the first raw PCM frame arrives.
            # Send 300 ms without pacing first, so USB/ROS scheduling jitter does
            # not turn the beginning of each synthesized reply into an underrun.
            prebuffer_frames = max(1, (sample_rate * 300 + frame_samples * 1000 - 1) //
                                    (frame_samples * 1000))
            self._playback_cancel.clear()
            self._playback_active.set()
            self._echo_suppressor.begin_playback()
            try:
                frame_index = 0
                while data := source.readframes(frame_samples):
                    if self._playback_cancel.is_set():
                        break
                    self._echo_suppressor.add_playback(data, sample_rate, channels)
                    timestamp_ns = self.get_clock().now().nanoseconds
                    msg = AudioFrame()
                    msg.header.stamp.sec = timestamp_ns // 1_000_000_000
                    msg.header.stamp.nanosec = timestamp_ns % 1_000_000_000
                    msg.header.frame_id = "minicpm_o"
                    msg.sample_rate = sample_rate
                    msg.channels = channels
                    msg.encoding = "pcm_s16le"
                    msg.frame_samples = len(data) // (2 * channels)
                    msg.data = array("B", data)
                    self._audio_output.publish(msg)
                    frame_index += 1
                    if frame_index >= prebuffer_frames:
                        time.sleep(msg.frame_samples / sample_rate)
                # 覆盖扬声器和房间混响的尾音。
                if not self._playback_cancel.is_set():
                    time.sleep(0.5)
            finally:
                self._playback_active.clear()
                self._echo_suppressor.finish_playback()

    def _run(self) -> None:
        while not self._stopping.is_set():
            event = self._events.get()
            if event is None:
                return
            try:
                self._handler(event)
            except Exception as error:
                self.get_logger().error(f"Agent 执行失败：{error}")

    def destroy_node(self) -> bool:
        self._stopping.set()
        if not self._events.full():
            self._events.put_nowait(None)
        self._worker.join(timeout=2)
        return super().destroy_node()
