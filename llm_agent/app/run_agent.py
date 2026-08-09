"""统一全模态 Agent ROS 2 Action Server 入口。"""

from __future__ import annotations

import fcntl
import os
import tempfile
from contextlib import contextmanager
from typing import Iterator, TextIO

import rclpy
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor

from llm_agent.runtime.factory import create_runtime
from llm_agent.transport.ros.agent_server import AgentActionServer
from llm_agent.transport.ros.interface_contract import load_agent_action_name

from .config import load_agent_config


@contextmanager
def _single_instance_lock() -> Iterator[TextIO]:
    """确保同一台主机上只运行一个 Agent Action Server。"""
    lock_path = os.environ.get(
        "CAR_AGENT_LOCK_FILE",
        os.path.join(tempfile.gettempdir(), "small_car_llm_agent.lock"),
    )
    lock_file = open(lock_path, "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "Agent Server 已在运行，拒绝启动重复的 ROS Action Server"
            ) from error
        yield lock_file
    finally:
        lock_file.close()


def main() -> None:
    try:
        with _single_instance_lock():
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
    except RuntimeError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
