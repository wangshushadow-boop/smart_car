#!/usr/bin/env python3
"""Always-on, wake-phrase voice loop for Hermes Agent on Raspberry Pi."""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd


LOG = logging.getLogger("hermes-car-voice")
STOP_REQUESTED = False

SAMPLE_RATE = int(os.getenv("CAR_VOICE_SAMPLE_RATE", "16000"))
PLAYBACK_SAMPLE_RATE = int(
    os.getenv("CAR_VOICE_PLAYBACK_SAMPLE_RATE", "48000")
)
BLOCK_MS = int(os.getenv("CAR_VOICE_BLOCK_MS", "100"))
BLOCK_SIZE = SAMPLE_RATE * BLOCK_MS // 1000
INPUT_DEVICE = int(os.getenv("CAR_VOICE_INPUT_DEVICE", "0"))
RMS_THRESHOLD = int(os.getenv("CAR_VOICE_RMS_THRESHOLD", "250"))
SPEECH_CONFIRM_MS = int(os.getenv("CAR_VOICE_SPEECH_CONFIRM_MS", "300"))
END_SILENCE_MS = int(os.getenv("CAR_VOICE_END_SILENCE_MS", "1200"))
IDLE_TIMEOUT_SECONDS = float(os.getenv("CAR_VOICE_IDLE_TIMEOUT_SECONDS", "30"))
ACTIVE_TIMEOUT_SECONDS = float(os.getenv("CAR_VOICE_ACTIVE_TIMEOUT_SECONDS", "90"))
MAX_UTTERANCE_SECONDS = float(os.getenv("CAR_VOICE_MAX_UTTERANCE_SECONDS", "20"))
PLAYBACK_DEVICE = os.getenv(
    "CAR_VOICE_PLAYBACK_DEVICE", "plughw:CARD=USB,DEV=0"
)
STT_PROVIDER = os.getenv("CAR_VOICE_STT_PROVIDER", "sensevoice")
SENSEVOICE_PYTHON = os.getenv(
    "CAR_VOICE_SENSEVOICE_PYTHON",
    "/home/ubuntu/.hermes/sensevoice-venv/bin/python",
)
SENSEVOICE_SCRIPT = os.getenv(
    "CAR_VOICE_SENSEVOICE_SCRIPT",
    "/home/ubuntu/.hermes/car_voice/sensevoice_transcribe.py",
)
CAMERA_CAPTURE_BIN = os.getenv(
    "CAR_VOICE_CAMERA_CAPTURE_BIN",
    "/home/ubuntu/smart_car/robot_host/build-v4l2/v4l2_capture",
)
CAMERA_DEVICE = os.getenv("CAR_VOICE_CAMERA_DEVICE", "/dev/video0")
CAMERA_WIDTH = int(os.getenv("CAR_VOICE_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("CAR_VOICE_CAMERA_HEIGHT", "720"))
CAMERA_IMAGE = Path(
    os.getenv(
        "CAR_VOICE_CAMERA_IMAGE",
        "/home/ubuntu/.hermes/run/car-voice/camera-latest.jpg",
    )
)
HERMES_BIN = os.getenv("HERMES_BIN", "/home/ubuntu/.hermes/venv/bin/hermes")
HERMES_PYTHON = os.getenv(
    "HERMES_PYTHON", "/home/ubuntu/.hermes/venv/bin/python"
)
RUN_DIR = Path(os.getenv("CAR_VOICE_RUN_DIR", "/home/ubuntu/.hermes/run/car-voice"))
WAKE_STT_MODEL = os.getenv(
    "CAR_VOICE_WAKE_STT_MODEL",
    "/home/ubuntu/.hermes/models/faster-whisper-tiny",
)
WAKE_ON_ANY_SPEECH = os.getenv(
    "CAR_VOICE_WAKE_ON_ANY_SPEECH", "true"
).lower() in {"1", "true", "yes", "on"}
INTENT_LLM_ENABLED = os.getenv(
    "CAR_VOICE_INTENT_LLM_ENABLED", "true"
).lower() in {"1", "true", "yes", "on"}

# 语音运动只接受固定动作，不允许大模型直接生成速度值。
MOTION_FORWARD_SPEED_MPS = min(
    0.6, max(0.0, float(os.getenv("CAR_VOICE_FORWARD_SPEED_MPS", "0.36")))
)
MOTION_REVERSE_SPEED_MPS = min(
    0.6, max(0.0, float(os.getenv("CAR_VOICE_REVERSE_SPEED_MPS", "0.25")))
)
MOTION_COMMANDS = {
    "forward": "好的，前进。",
    "backward": "好的，后退。",
    "left": "好的，左转。",
    "right": "好的，右转。",
}

WAKE_PHRASES = tuple(
    phrase.strip()
    for phrase in os.getenv(
        "CAR_VOICE_WAKE_PHRASES", "小车,晓车,校车,像车,想车,小撤"
    ).split(",")
    if phrase.strip()
)
EXIT_PHRASES = tuple(
    phrase.strip()
    for phrase in os.getenv(
        "CAR_VOICE_EXIT_PHRASES", "再见,退出对话,结束对话,休息吧,不用了"
    ).split(",")
    if phrase.strip()
)
VISION_PHRASES = tuple(
    phrase.strip()
    for phrase in os.getenv(
        "CAR_VOICE_VISION_PHRASES",
        "看看前面,看一下前面,看下前面,前面有什么,你看到了什么,"
        "你看到了啥,看见什么,看见啥,能看到什么,能看到啥,眼前有什么,"
        "看看,看一下,看一看,拍张照片,拍照,重新看一下,重新看,"
        "打开相机,调用相机,摄像头,相机",
    ).split(",")
    if phrase.strip()
)

SUPPORTED_INTENTS = {
    "camera.inspect",
    "conversation.chat",
    "conversation.exit",
    "music.play",
    "music.stop",
    "motion.command",
    "volume.adjust",
    "navigation.request",
    "unknown",
}


@dataclass(frozen=True)
class IntentResult:
  name: str
  confidence: float
  slots: dict[str, object]
  source: str


class RosMotionPublisher:
  """调用标准 ROS2 定距/定角 Action，并保留立即停车入口。"""

  def __init__(self) -> None:
    import rclpy
    from geometry_msgs.msg import TwistStamped
    from nav2_msgs.action import DriveOnHeading, Spin
    from rclpy.action import ActionClient

    self._rclpy = rclpy
    self._twist_type = TwistStamped
    self._drive_type = DriveOnHeading
    self._spin_type = Spin
    self._rclpy.init(args=None)
    self._node = self._rclpy.create_node("hermes_voice_motion")
    self._stop_publisher = self._node.create_publisher(
        TwistStamped, "/cmd_vel", 10
    )
    self._drive_client = ActionClient(
        self._node, DriveOnHeading, "/drive_on_heading"
    )
    self._spin_client = ActionClient(self._node, Spin, "/spin")
    self._goal_handle = None
    self._done = threading.Event()
    self._shutdown = False
    self._thread = threading.Thread(
        target=self._spin_loop, name="voice-motion-action", daemon=True
    )
    self._thread.start()

  def start(self, action: str, amount: float) -> bool:
    """发送一个定距或定角目标；amount 分别使用米或弧度。"""
    if self._goal_handle is not None:
      self._goal_handle.cancel_goal_async()
      self._goal_handle = None
    self._done.clear()

    if action in {"forward", "backward"}:
      if not self._drive_client.wait_for_server(timeout_sec=2.0):
        LOG.error("DriveOnHeading action server unavailable")
        return False
      goal = self._drive_type.Goal()
      goal.target.x = abs(amount) if action == "forward" else -abs(amount)
      goal.speed = (
          MOTION_FORWARD_SPEED_MPS
          if action == "forward"
          else MOTION_REVERSE_SPEED_MPS
      )
      goal.time_allowance.sec = 20
      future = self._drive_client.send_goal_async(goal)
      future.add_done_callback(self._on_goal_response)
      LOG.info("Distance action: action=%s distance=%.3f m", action, amount)
      return True

    if action in {"left", "right"}:
      if not self._spin_client.wait_for_server(timeout_sec=2.0):
        LOG.error("Spin action server unavailable")
        return False
      goal = self._spin_type.Goal()
      goal.target_yaw = abs(amount) if action == "left" else -abs(amount)
      goal.time_allowance.sec = 20
      future = self._spin_client.send_goal_async(goal)
      future.add_done_callback(self._on_goal_response)
      LOG.info("Angle action: action=%s angle=%.3f rad", action, amount)
      return True

    return False

  def stop(self) -> None:
    """取消当前 Action，并通过直接速度入口发送零速度。"""
    if self._goal_handle is not None:
      self._goal_handle.cancel_goal_async()
      self._goal_handle = None
    command = self._twist_type()
    command.header.stamp = self._node.get_clock().now().to_msg()
    command.header.frame_id = "base_link"
    self._stop_publisher.publish(command)
    self._done.set()
    LOG.info("Motion stopped")

  def wait(self, timeout: float) -> bool:
    """等待动作返回，主要供端到端测试命令使用。"""
    return self._done.wait(timeout)

  def close(self) -> None:
    """停车并释放 ROS2 节点。"""
    self.stop()
    self._shutdown = True
    self._thread.join(timeout=2.0)
    self._node.destroy_node()
    if self._rclpy.ok():
      self._rclpy.shutdown()

  def _on_goal_response(self, future: object) -> None:
    handle = future.result()
    if not handle.accepted:
      LOG.error("Motion action rejected")
      self._done.set()
      return
    self._goal_handle = handle
    result_future = handle.get_result_async()
    result_future.add_done_callback(self._on_result)

  def _on_result(self, future: object) -> None:
    wrapped = future.result()
    LOG.info("Motion action finished: status=%s", wrapped.status)
    self._goal_handle = None
    self._done.set()

  def _spin_loop(self) -> None:
    while not self._shutdown:
      self._rclpy.spin_once(self._node, timeout_sec=0.1)


MOTION_PUBLISHER: RosMotionPublisher | None = None


def request_stop(_signum: int, _frame: object) -> None:
  global STOP_REQUESTED
  STOP_REQUESTED = True


def normalize_text(text: str) -> str:
  return re.sub(r"[^\w\u4e00-\u9fff]", "", text).lower()


def contains_phrase(text: str, phrases: tuple[str, ...]) -> bool:
  normalized = normalize_text(text)
  return any(normalize_text(phrase) in normalized for phrase in phrases)


def parse_chinese_number(value: str) -> float | None:
  """解析语音控制常用的简单中文数字，范围覆盖零到九百九十九。"""
  if value == "半":
    return 0.5
  digits = {
      "零": 0,
      "一": 1,
      "二": 2,
      "两": 2,
      "三": 3,
      "四": 4,
      "五": 5,
      "六": 6,
      "七": 7,
      "八": 8,
      "九": 9,
  }
  if all(character in digits for character in value):
    result = 0
    for character in value:
      result = result * 10 + digits[character]
    return float(result)

  total = 0
  current = 0
  for character in value:
    if character in digits:
      current = digits[character]
    elif character == "十":
      total += (current or 1) * 10
      current = 0
    elif character == "百":
      total += (current or 1) * 100
      current = 0
    else:
      return None
  return float(total + current)


def parse_motion_amount(text: str, action: str) -> float:
  """从语句提取米、厘米、毫米或角度，未指定时返回安全默认值。"""
  match = re.search(
      r"([0-9]+(?:\.[0-9]+)?|[零一二两三四五六七八九十百半]+)"
      r"\s*(厘米|公分|毫米|米|度)",
      text,
  )
  if match is None:
    return 0.5 if action in {"forward", "backward"} else 1.5707963268

  token, unit = match.groups()
  try:
    number = float(token)
  except ValueError:
    parsed = parse_chinese_number(token)
    if parsed is None:
      return 0.5 if action in {"forward", "backward"} else 1.5707963268
    number = parsed

  if unit in {"厘米", "公分"}:
    return number / 100.0
  if unit == "毫米":
    return number / 1000.0
  if unit == "度":
    return number * 3.141592653589793 / 180.0
  return number


def is_vision_request(text: str) -> bool:
  """Detect colloquial Chinese requests that need a fresh camera frame."""
  if contains_phrase(text, VISION_PHRASES):
    return True

  normalized = normalize_text(text)
  visual_actions = ("看", "看到", "看见", "瞧", "瞅", "拍", "观察", "识别")
  visual_targets = (
      "什么",
      "啥",
      "前面",
      "眼前",
      "周围",
      "画面",
      "图像",
      "图片",
      "照片",
      "这个",
      "那个",
      "哪里",
      "哪儿",
      "多远",
      "距离",
  )
  has_action = any(term in normalized for term in visual_actions)
  has_target = any(term in normalized for term in visual_targets)
  distance_request = any(term in normalized for term in ("多远", "距离")) and any(
      term in normalized for term in ("这", "那", "前面", "眼前")
  )
  directional_look = any(term in normalized for term in ("向前", "往前")) and any(
      term in normalized for term in visual_actions
  )
  return (has_action and has_target) or distance_request or directional_look


def match_local_intent(text: str) -> IntentResult | None:
  """Return a high-confidence local intent, or None for semantic routing."""
  normalized = normalize_text(text)

  if contains_phrase(text, EXIT_PHRASES):
    return IntentResult("conversation.exit", 1.0, {}, "local_rule")

  # 停车优先于其他运动；“停止音乐”仍交给后面的音乐规则处理。
  motion_stop_phrases = {"停止", "停车", "停下", "别动", "不要动", "小车停止"}
  if normalized in motion_stop_phrases:
    return IntentResult(
        "motion.command", 1.0, {"action": "stop"}, "local_rule"
    )

  # “向前看”等视觉请求不能被“向前”运动规则抢先匹配。
  if is_vision_request(text):
    return IntentResult(
        "camera.inspect", 1.0, {"question": text}, "local_rule"
    )

  # 基础运动只接受无目的地的短动作；带地点的语句交给导航意图处理。
  navigation_targets = (
      "桌子",
      "门口",
      "厨房",
      "客厅",
      "卧室",
      "旁边",
      "那里",
      "那边",
      "位置",
      "目的地",
  )
  motion_phrases = (
      ("backward", ("后退", "倒退", "向后", "往后")),
      ("left", ("左转", "向左转", "往左转")),
      ("right", ("右转", "向右转", "往右转")),
      ("forward", ("前进", "向前", "往前")),
  )
  if not any(target in normalized for target in navigation_targets):
    for action, phrases in motion_phrases:
      if any(phrase in normalized for phrase in phrases):
        return IntentResult(
            "motion.command",
            1.0,
            {
                "action": action,
                "amount": parse_motion_amount(text, action),
            },
            "local_rule",
        )

  music_words = ("音乐", "歌曲", "歌", "萱草花", "播放")
  if any(word in normalized for word in music_words):
    if any(word in normalized for word in ("停止", "暂停", "关闭", "别放", "不放")):
      return IntentResult("music.stop", 0.98, {}, "local_rule")
    if any(word in normalized for word in ("播放", "放一首", "放首", "听", "来一首")):
      return IntentResult(
          "music.play", 0.98, {"request": text}, "local_rule"
      )

  if "音量" in normalized:
    direction = "unknown"
    if any(word in normalized for word in ("最大", "调大", "大一点", "提高")):
      direction = "up"
    elif any(word in normalized for word in ("最小", "调小", "小一点", "降低")):
      direction = "down"
    return IntentResult(
        "volume.adjust", 0.98, {"direction": direction}, "local_rule"
    )

  navigation_verbs = ("导航", "前往", "移动到", "开到", "走到")
  navigation_targets = ("桌子", "门口", "厨房", "客厅", "前面", "旁边", "那边")
  if any(word in normalized for word in navigation_verbs) or (
      any(word in normalized for word in ("去", "到"))
      and any(word in normalized for word in navigation_targets)
  ):
    return IntentResult(
        "navigation.request", 0.95, {"target_text": text}, "local_rule"
    )

  return None


def looks_like_action_request(text: str) -> bool:
  normalized = normalize_text(text)
  hints = (
      "看",
      "瞧",
      "瞅",
      "相机",
      "摄像头",
      "照片",
      "前面",
      "周围",
      "播放",
      "音乐",
      "歌曲",
      "音量",
      "停止",
      "暂停",
      "前进",
      "后退",
      "左转",
      "右转",
      "停车",
      "导航",
      "前往",
      "移动",
      "帮我",
      "给我",
      "替我",
  )
  return any(hint in normalized for hint in hints)


def capture_camera() -> Path | None:
  """Capture one MJPEG frame from the USB camera."""
  CAMERA_IMAGE.parent.mkdir(parents=True, exist_ok=True)
  command = [
      CAMERA_CAPTURE_BIN,
      CAMERA_DEVICE,
      "mjpg",
      str(CAMERA_IMAGE),
      str(CAMERA_WIDTH),
      str(CAMERA_HEIGHT),
  ]
  LOG.info(
      "Capturing camera image: device=%s, size=%sx%s",
      CAMERA_DEVICE,
      CAMERA_WIDTH,
      CAMERA_HEIGHT,
  )
  try:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
  except (OSError, subprocess.SubprocessError) as error:
    LOG.error("Camera capture failed: %s", error)
    return None

  if completed.returncode != 0 or not CAMERA_IMAGE.is_file():
    detail = completed.stderr.strip() or completed.stdout.strip()
    LOG.error("Camera capture failed: %s", detail or "unknown error")
    return None

  CAMERA_IMAGE.chmod(0o600)
  LOG.info("Camera image ready: %s", CAMERA_IMAGE)
  return CAMERA_IMAGE


def save_wav(path: Path, samples: np.ndarray) -> None:
  with wave.open(str(path), "wb") as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(SAMPLE_RATE)
    wav_file.writeframes(samples.astype(np.int16).tobytes())


def record_utterance(wait_timeout: float) -> Path | None:
  """Wait for speech and record until silence using a small pre-roll buffer."""
  pre_roll_blocks = max(1, 500 // BLOCK_MS)
  confirm_blocks = max(1, SPEECH_CONFIRM_MS // BLOCK_MS)
  end_silence_blocks = max(1, END_SILENCE_MS // BLOCK_MS)
  max_blocks = max(1, int(MAX_UTTERANCE_SECONDS * 1000 // BLOCK_MS))
  pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_blocks)
  frames: list[np.ndarray] = []
  voiced_run = 0
  silence_run = 0
  started = False
  deadline = time.monotonic() + wait_timeout

  with sd.InputStream(
      device=INPUT_DEVICE,
      samplerate=SAMPLE_RATE,
      channels=1,
      dtype="int16",
      blocksize=BLOCK_SIZE,
  ) as stream:
    while not STOP_REQUESTED and time.monotonic() < deadline:
      data, overflowed = stream.read(BLOCK_SIZE)
      if overflowed:
        LOG.warning("Audio input overflow")
      block = data[:, 0].copy()
      rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
      is_voiced = rms >= RMS_THRESHOLD

      if not started:
        pre_roll.append(block)
        voiced_run = voiced_run + 1 if is_voiced else 0
        if voiced_run >= confirm_blocks:
          started = True
          frames.extend(pre_roll)
          LOG.info("Speech detected (RMS %.0f)", rms)
        continue

      frames.append(block)
      silence_run = 0 if is_voiced else silence_run + 1
      if silence_run >= end_silence_blocks or len(frames) >= max_blocks:
        break

  if not started or not frames:
    return None

  samples = np.concatenate(frames)
  RUN_DIR.mkdir(parents=True, exist_ok=True)
  path = RUN_DIR / f"utterance-{int(time.time() * 1000)}.wav"
  save_wav(path, samples)
  return path


def transcribe(path: Path, model: str | None = None) -> str:
  if STT_PROVIDER == "sensevoice":
    try:
      completed = subprocess.run(
          [SENSEVOICE_PYTHON, SENSEVOICE_SCRIPT, str(path)],
          capture_output=True,
          text=True,
          timeout=60,
          check=False,
      )
      result = json.loads(completed.stdout)
      if completed.returncode != 0 or not result.get("success"):
        LOG.error(
            "SenseVoice failed: %s",
            result.get("error", completed.stderr.strip() or "unknown error"),
        )
        return ""
      text = str(result.get("text", "")).strip()
      if not normalize_text(text):
        text = ""
      LOG.info(
          "SenseVoice transcript (%.3fs): %s",
          float(result.get("elapsed_seconds", 0)),
          text or "<empty>",
      )
      return text
    except (json.JSONDecodeError, OSError, subprocess.SubprocessError) as error:
      LOG.error("SenseVoice failed: %s", error)
      return ""

  helper = (
      "import json,sys; "
      "from tools.transcription_tools import transcribe_audio; "
      "model=sys.argv[2] or None; "
      "print(json.dumps(transcribe_audio(sys.argv[1], model=model)))"
  )
  try:
    completed = subprocess.run(
        [HERMES_PYTHON, "-c", helper, str(path), model or ""],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    result = json.loads(completed.stdout)
  except (json.JSONDecodeError, OSError, subprocess.SubprocessError) as error:
    LOG.error("STT failed: %s", error)
    return ""
  if completed.returncode != 0 or not result.get("success"):
    LOG.error("STT failed: %s", result.get("error", completed.stderr.strip()))
    return ""
  text = str(result.get("transcript", "")).strip()
  LOG.info("Transcript: %s", text or "<empty>")
  return text


def parse_hermes_output(stdout: str, stderr: str = "") -> tuple[str, str | None]:
  ansi_escape = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
  clean = ansi_escape.sub("", stdout).strip()
  session_id = None
  response_lines: list[str] = []
  for line in (clean + "\n" + ansi_escape.sub("", stderr)).splitlines():
    stripped = line.strip()
    if stripped.startswith("session_id:"):
      session_id = stripped.split(":", 1)[1].strip()
    elif "tirith security scanner" in stripped:
      continue
    elif stripped.startswith("↻ Resumed session"):
      continue
    elif not stripped.startswith("session_title:"):
      response_lines.append(line)
  return "\n".join(response_lines).strip(), session_id


def extract_json_object(text: str) -> dict[str, object] | None:
  decoder = json.JSONDecoder()
  for index, char in enumerate(text):
    if char != "{":
      continue
    try:
      value, _ = decoder.raw_decode(text[index:])
    except json.JSONDecodeError:
      continue
    if isinstance(value, dict):
      return value
  return None


def classify_intent_with_llm(text: str) -> IntentResult | None:
  prompt = (
      "你是智能小车的意图分类器，只能输出单行 JSON，不要解释。"
      "格式：{\"intent\":\"...\",\"confidence\":0.0,\"slots\":{}}。"
      "intent 只能是 camera.inspect、conversation.chat、conversation.exit、"
      "music.play、music.stop、volume.adjust、"
      "navigation.request、unknown。"
      "camera.inspect 表示需要观察相机画面、拍照、判断眼前物体或距离；"
      "navigation.request 表示要求小车移动到某处；其余按名称判断。"
      "slots 中只提取用户明确说出的参数，不执行任何动作。\n"
      f"用户原话：{text}"
  )
  command = [
      HERMES_BIN,
      "chat",
      "-q",
      prompt,
      "-Q",
      "--source",
      "tool",
      "--max-turns",
      "1",
      "--ignore-rules",
  ]
  try:
    completed = subprocess.run(
        command,
        cwd="/home/ubuntu",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
  except (OSError, subprocess.SubprocessError) as error:
    LOG.error("Intent classifier failed: %s", error)
    return None

  if completed.returncode != 0:
    LOG.error("Intent classifier failed: %s", completed.stderr.strip())
    return None

  payload = extract_json_object(completed.stdout)
  if payload is None:
    LOG.error("Intent classifier returned no JSON: %s", completed.stdout.strip())
    return None

  name = str(payload.get("intent", "unknown"))
  if name not in SUPPORTED_INTENTS:
    LOG.error("Intent classifier returned unsupported intent: %s", name)
    return None
  try:
    confidence = min(1.0, max(0.0, float(payload.get("confidence", 0.0))))
  except (TypeError, ValueError):
    confidence = 0.0
  slots_value = payload.get("slots", {})
  slots = slots_value if isinstance(slots_value, dict) else {}
  return IntentResult(name, confidence, slots, "minimax")


def route_intent(text: str) -> IntentResult:
  local = match_local_intent(text)
  if local is not None:
    return local
  if INTENT_LLM_ENABLED and looks_like_action_request(text):
    semantic = classify_intent_with_llm(text)
    if semantic is not None and semantic.confidence >= 0.6:
      return semantic
  return IntentResult("conversation.chat", 1.0, {}, "default_chat")


def ask_hermes(
    text: str, session_id: str | None, image_path: Path | None = None
) -> tuple[str, str | None]:
  user_prompt = text
  if image_path is not None:
    user_prompt = (
        "本轮附带的是小车刚刚拍摄的前方相机图片。请直接观察图片，"
        "结合用户的问题简短回答，不要声称无法访问相机。\n"
        f"用户说：{text}"
    )
  prompt = user_prompt
  command = [
      HERMES_BIN,
      "chat",
      "-q",
      prompt,
      "-Q",
      "--source",
      "tool",
      "--max-turns",
      "12",
  ]
  if image_path is not None:
    command.extend(["--image", str(image_path)])
  if session_id:
    command.extend(["--resume", session_id])
  else:
    prompt = (
        "你是安装在智能小车上的中文语音助手。回答应简短、自然、适合直接朗读，"
        "不要使用 Markdown。当前阶段禁止控制电机或 STM32，但可以观察本轮附带的"
        "小车相机图片。\n"
        f"{user_prompt}"
    )
    command[3] = prompt

  LOG.info(
      "Calling Hermes%s%s",
      f" session {session_id}" if session_id else "",
      " with camera image" if image_path is not None else "",
  )
  try:
    completed = subprocess.run(
        command,
        cwd="/home/ubuntu",
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
  except subprocess.TimeoutExpired:
    LOG.error("Hermes request timed out")
    return "请求超时了，请再说一次。", session_id

  if completed.returncode != 0:
    LOG.error("Hermes failed: %s", completed.stderr.strip())
    return "连接模型失败了，请稍后再试。", session_id

  response, new_session_id = parse_hermes_output(
      completed.stdout, completed.stderr
  )
  if not response:
    response = "我没有听清楚，请再说一次。"
  LOG.info("Hermes response: %s", response)
  return response, new_session_id or session_id


def speak(text: str) -> None:
  RUN_DIR.mkdir(parents=True, exist_ok=True)
  mp3_path = RUN_DIR / "reply.mp3"
  try:
    helper = (
        "import sys; from tools.tts_tool import text_to_speech_tool; "
        "print(text_to_speech_tool(sys.argv[1], sys.argv[2]))"
    )
    completed = subprocess.run(
        [HERMES_PYTHON, "-c", helper, text, str(mp3_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    result = json.loads(completed.stdout)
    if completed.returncode != 0:
      raise RuntimeError(completed.stderr.strip() or "TTS process failed")
    if not result.get("success"):
      raise RuntimeError(result.get("error", "TTS failed"))
    # mpg123 直接解码并输出 MP3，避免为一段提示音引入完整 FFmpeg。
    subprocess.run(
        ["mpg123", "-q", "-a", PLAYBACK_DEVICE, str(mp3_path)],
        check=True,
        env={**os.environ, "HOME": str(RUN_DIR)},
        timeout=60,
    )
  except (json.JSONDecodeError, OSError, RuntimeError, subprocess.SubprocessError) as error:
    LOG.error("TTS/playback failed: %s", error)


def process_user_turn(
    text: str,
    session_id: str | None,
    intent: IntentResult | None = None,
    prefetched_image: Path | None = None,
) -> tuple[str | None, bool]:
  intent = intent or route_intent(text)
  LOG.info(
      "Intent: name=%s, confidence=%.2f, source=%s, slots=%s",
      intent.name,
      intent.confidence,
      intent.source,
      json.dumps(intent.slots, ensure_ascii=False),
  )

  if intent.name == "conversation.exit":
    speak("好的，再见。")
    return session_id, True

  if intent.name == "camera.inspect":
    image_path = prefetched_image or capture_camera()
    if image_path is None:
      speak("相机抓图失败了，请检查相机连接。")
      return session_id, False
    response, session_id = ask_hermes(text, session_id, image_path)
    speak(response)
    return session_id, False

  if intent.name in {"music.play", "music.stop"}:
    speak("我识别到音乐控制请求了，但音乐控制还没有接入。")
    return session_id, False
  if intent.name == "volume.adjust":
    speak("我识别到音量调节请求了，但语音音量控制还没有接入。")
    return session_id, False
  if intent.name == "motion.command":
    if MOTION_PUBLISHER is None:
      speak("运动控制暂时不可用。")
      return session_id, False
    if intent.source != "local_rule":
      speak("运动指令没有通过本地安全规则。")
      return session_id, False
    action = str(intent.slots.get("action", "stop"))
    if action == "stop":
      MOTION_PUBLISHER.stop()
      speak("已停车。")
      return session_id, False
    command = MOTION_COMMANDS.get(action)
    if command is None:
      speak("这个运动指令还不支持。")
      return session_id, False
    amount = float(intent.slots.get("amount", parse_motion_amount(text, action)))
    if not MOTION_PUBLISHER.start(action, amount):
      speak("运动控制节点暂时不可用。")
      return session_id, False
    speak(command)
    return session_id, False
  if intent.name == "navigation.request":
    speak("目前只支持前进、后退、左转、右转和停止。")
    return session_id, False

  response, session_id = ask_hermes(text, session_id)
  speak(response)
  return session_id, False


def conversation_loop(
    initial_text: str | None = None,
    initial_image: Path | None = None,
    initial_intent: IntentResult | None = None,
) -> None:
  session_id: str | None = None
  if initial_text:
    session_id, should_exit = process_user_turn(
        initial_text, session_id, initial_intent, initial_image
    )
    if should_exit:
      return
  else:
    speak("我在，请说。")
  active_deadline = time.monotonic() + ACTIVE_TIMEOUT_SECONDS

  while not STOP_REQUESTED and time.monotonic() < active_deadline:
    path = record_utterance(IDLE_TIMEOUT_SECONDS)
    if path is None:
      LOG.info("Conversation idle timeout; returning to wake mode")
      speak("我先休息了，需要时再叫我。")
      return

    text = transcribe(path)
    path.unlink(missing_ok=True)
    if not text:
      continue

    active_deadline = time.monotonic() + ACTIVE_TIMEOUT_SECONDS
    session_id, should_exit = process_user_turn(text, session_id)
    if should_exit:
      return

  if not STOP_REQUESTED:
    LOG.info("Conversation maximum active time reached")
    speak("这次对话先到这里，需要时再叫我。")


def main() -> int:
  global MOTION_PUBLISHER
  logging.basicConfig(
      level=os.getenv("CAR_VOICE_LOG_LEVEL", "INFO"),
      format="%(asctime)s %(levelname)s %(message)s",
  )
  signal.signal(signal.SIGTERM, request_stop)
  signal.signal(signal.SIGINT, request_stop)
  RUN_DIR.mkdir(parents=True, exist_ok=True)

  try:
    MOTION_PUBLISHER = RosMotionPublisher()
  except (ImportError, RuntimeError) as error:
    LOG.error("ROS2 motion publisher init failed: %s", error)
    return 1

  LOG.info(
      "Voice daemon ready: input=%s at %s Hz, playback=%s at %s Hz, "
      "stt=%s, camera=%s, threshold=%s, wake=%s, wake_on_any_speech=%s",
      INPUT_DEVICE,
      SAMPLE_RATE,
      PLAYBACK_DEVICE,
      PLAYBACK_SAMPLE_RATE,
      STT_PROVIDER,
      CAMERA_DEVICE,
      RMS_THRESHOLD,
      ",".join(WAKE_PHRASES),
      WAKE_ON_ANY_SPEECH,
  )
  try:
    while not STOP_REQUESTED:
      try:
        path = record_utterance(3600)
        if path is None:
          continue
        text = transcribe(path, WAKE_STT_MODEL)
        path.unlink(missing_ok=True)
        phrase_matched = contains_phrase(text, WAKE_PHRASES)
        if phrase_matched or (WAKE_ON_ANY_SPEECH and bool(text)):
          LOG.info(
              "Wake accepted (%s)",
              "phrase" if phrase_matched else "debug any-speech mode",
          )
          initial_intent = route_intent(text)
          if initial_intent.name != "conversation.chat":
            wake_image = (
                capture_camera()
                if initial_intent.name == "camera.inspect"
                else None
            )
            conversation_loop(text, wake_image, initial_intent)
          else:
            conversation_loop()
        elif text:
          LOG.info("Wake phrase not found")
      except Exception:
        LOG.exception("Voice loop error; retrying")
        time.sleep(2)
  finally:
    MOTION_PUBLISHER.close()
    MOTION_PUBLISHER = None

  LOG.info("Voice daemon stopped")
  return 0


def run_motion_test(text: str) -> int:
  """使用正式意图规则和 ROS Action 执行一次定距或定角动作。"""
  global MOTION_PUBLISHER

  logging.basicConfig(
      level=os.getenv("CAR_VOICE_LOG_LEVEL", "INFO"),
      format="%(asctime)s %(levelname)s %(message)s",
  )
  intent = route_intent(text)
  if intent.name != "motion.command" or intent.source != "local_rule":
    LOG.error("Motion test rejected: text=%s intent=%s", text, intent.name)
    return 1

  action = str(intent.slots.get("action", "stop"))
  command = MOTION_COMMANDS.get(action)
  try:
    MOTION_PUBLISHER = RosMotionPublisher()
    if action == "stop":
      MOTION_PUBLISHER.stop()
    elif command is not None:
      amount = float(
          intent.slots.get("amount", parse_motion_amount(text, action))
      )
      LOG.info(
          "Motion test: text=%s action=%s amount=%.3f",
          text,
          action,
          amount,
      )
      if not MOTION_PUBLISHER.start(action, amount):
        return 1
      if not MOTION_PUBLISHER.wait(25.0):
        LOG.error("Motion test timeout")
        return 1
    else:
      LOG.error("Unsupported motion test action: %s", action)
      return 1
  finally:
    if MOTION_PUBLISHER is not None:
      MOTION_PUBLISHER.close()
      MOTION_PUBLISHER = None
  return 0


if __name__ == "__main__":
  if len(sys.argv) >= 3 and sys.argv[1] == "--test-motion":
    raise SystemExit(run_motion_test(" ".join(sys.argv[2:])))
  if len(sys.argv) >= 3 and sys.argv[1] == "--classify-intent":
    classified = route_intent(" ".join(sys.argv[2:]))
    print(
        json.dumps(
            {
                "intent": classified.name,
                "confidence": classified.confidence,
                "slots": classified.slots,
                "source": classified.source,
            },
            ensure_ascii=False,
        )
    )
    raise SystemExit(0)
  raise SystemExit(main())
