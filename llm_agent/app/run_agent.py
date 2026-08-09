"""统一全模态 Agent ROS 2 Action Server 入口。"""

from __future__ import annotations

import rclpy
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor

from llm_agent.runtime.factory import create_runtime
from llm_agent.transport.ros.agent_server import AgentActionServer
from llm_agent.transport.ros.interface_contract import load_agent_action_name

from .config import load_agent_config


def main() -> None:
    rclpy.init()
    config = load_agent_config()
    runtime, generation_name, speech_name = create_runtime(config)
    node = AgentActionServer(
        runtime,
        load_agent_action_name(),
        max_inline_bytes=config.runtime.max_inline_bytes,
    )
    node.get_logger().info(
        f"Agent 已启动：generation={generation_name}, speech={speech_name}"
    )
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        runtime.stop()
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
