"""统一全模态 Agent ROS 2 Action Server 入口。

这是 `llm_agent` 在 WSL 上的唯一进程入口，启动顺序：
1. 单实例锁：防止同一台主机上重复启动 Action Server 抢占 `/car/agent/run`。
2. 配置加载：根据 `agent.yaml` 与环境变量构建 `AgentConfig`。
3. Runtime 装配：选择 Provider、扫描 Skill、注册 Tool 并构造唯一 Agent Loop。
4. Gateway 装配：增加请求幂等和同 Session 串行控制。
5. Action Server 启动：在 ROS 2 多线程 Executor 上提供唯一 Action 接口。
5. 信号处理：`Ctrl+C` 或 ROS 外部关闭信号触发优雅退出。
"""

from __future__ import annotations

import fcntl
import logging
import os
import tempfile
from contextlib import contextmanager
from typing import Iterator, TextIO

import rclpy
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor

from llm_agent.gateway import AgentGateway
from llm_agent.runtime.agent_loop import create_runtime
from llm_agent.transport.ros.audio_output_client import RosAudioOutputClient
from llm_agent.transport.ros.run_agent_server import (
    AgentActionServer,
    load_agent_action_name,
    load_audio_service_name,
    load_robot_tool_action_name,
)
from llm_agent.transport.ros.robot_tool_client import RosRobotToolClient

from llm_agent.config import load_agent_config


def _configure_model_output_logger() -> None:
    """将模型原始文本输出到前台终端，避免被 ROS 日志配置吞掉。

    `AgentLoop` 在解析每轮结构化决策前写入 `llm_agent.model_output` logger；
    这里独立挂一个 StreamHandler，
    不走 ROS 的日志系统，保证调试时能直接看到模型原始 JSON。
    """

    logger = logging.getLogger("llm_agent.model_output")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] [model_output] %(message)s"))
    logger.addHandler(handler)


@contextmanager
def _single_instance_lock() -> Iterator[TextIO]:
    """确保同一台主机上只运行一个 Agent Action Server。

    使用 `fcntl.flock` 排他锁，路径可通过 `CAR_AGENT_LOCK_FILE` 自定义。
    如果锁已被持有，立即抛 `RuntimeError`，由 `main()` 转 `SystemExit`。
    这样可以避免两个进程同时监听 `/car/agent/run` 互相抢答 Goal。
    """
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
    """进程入口：装配 Runtime 并运行 Action Server 直到收到退出信号。"""
    try:
        with _single_instance_lock():
            _configure_model_output_logger()
            rclpy.init()
            config = load_agent_config()
            # 生产环境的运动 Tool 通过独立 ROS 客户端访问树莓派安全 Gateway。
            robot_tool_client = RosRobotToolClient(load_robot_tool_action_name())
            audio_output_client = RosAudioOutputClient(load_audio_service_name())
            runtime, generation_name, speech_name = create_runtime(
                config,
                robot_tool_executor=robot_tool_client,
                audio_output=audio_output_client,
            )
            gateway = AgentGateway(runtime)
            node = AgentActionServer(
                gateway,
                load_agent_action_name(),
                max_inline_bytes=config.runtime.max_inline_bytes,
            )
            node.get_logger().info(
                f"Agent 已启动：generation_model={generation_name}, "
                f"speech={speech_name}"
            )
            # 多线程 Executor：feedback publish 与 goal 处理不会互相阻塞。
            executor = MultiThreadedExecutor(num_threads=4)
            executor.add_node(node)
            executor.add_node(robot_tool_client)
            executor.add_node(audio_output_client)
            try:
                executor.spin()
            except (KeyboardInterrupt, ExternalShutdownException):
                # Ctrl+C 或 ROS 外部关闭信号都走优雅退出路径。
                pass
            finally:
                # Gateway 先拒绝新请求，再由 Runtime 关闭持久化 SessionStore。
                gateway.stop()
                executor.shutdown()
                node.destroy_node()
                robot_tool_client.destroy_node()
                audio_output_client.destroy_node()
                if rclpy.ok():
                    rclpy.shutdown()
    except RuntimeError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
