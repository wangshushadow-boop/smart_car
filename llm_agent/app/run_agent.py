"""Application entry point: ROS events -> Agent runtime -> ROS audio output."""

from __future__ import annotations

from threading import Event

import rclpy
from rclpy._rclpy_pybind11 import RCLError
from rclpy.executors import ExternalShutdownException

from llm_agent.agent.graph import build_graph
from llm_agent.agent.runtime import AgentRuntime
from llm_agent.input.ros_perception import RosPerceptionInput


def main() -> None:
    rclpy.init()
    cancelled = Event()
    runtime = AgentRuntime(build_graph(cancelled=cancelled), cancelled=cancelled)
    node: RosPerceptionInput | None = None

    def handle(event) -> None:
        result = runtime.handle(event)
        answer = result.get("answer", "（无回复）")
        print(f"\nMiniCPM-o：{answer}", flush=True)
        if node is not None and result.get("answer_wav"):
            node.publish_wav(result["answer_wav"])

    node = RosPerceptionInput(handle)
    node.get_logger().info("Agent 已启动：订阅树莓派音视频，并回传模型语音")
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException, RCLError):
        pass
    finally:
        runtime.cancel()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
