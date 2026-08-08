"""Application entry point: ROS events -> Agent runtime -> ROS audio output."""

from __future__ import annotations

from threading import Event

import rclpy
from rclpy._rclpy_pybind11 import RCLError
from rclpy.executors import ExternalShutdownException

from llm_agent.agent.graph import build_graph
from llm_agent.agent.runtime import AgentRuntime
from llm_agent.input.ros_perception import RosPerceptionInput
from llm_agent.models.registry import select_backends

from .config import load_agent_config


def main() -> None:
    rclpy.init()
    cancelled = Event()
    config = load_agent_config()
    generation, speech = select_backends(config)
    runtime = AgentRuntime(
        build_graph(model=generation, tts=speech, cancelled=cancelled),
        cancelled=cancelled,
    )
    node: RosPerceptionInput | None = None

    def handle(event) -> None:
        result = runtime.handle(event)
        answer = result.get("answer", "（无回复）")
        provider = result.get("generation_backend", generation.provider_name)
        print(f"\n{provider}：{answer}", flush=True)
        if node is not None and result.get("answer_wav"):
            node.publish_wav(result["answer_wav"])

    node = RosPerceptionInput(handle)
    node.get_logger().info(
        f"Agent 已启动：generation={generation.provider_name}, "
        f"speech={speech.provider_name}"
    )
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
