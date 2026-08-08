"""运行入口：ROS 事件 → LangGraph → MiniCPM-o 回复。"""
import rclpy
from rclpy.executors import ExternalShutdownException
from .graph import build_graph
from llm_agent.input.ros_perception import RosPerceptionInput


def main() -> None:
    rclpy.init()
    graph = build_graph()
    def handle(event: dict) -> None:
        result = graph.invoke(event)
        answer = result.get("answer", "（无回复）")
        print(f"\nMiniCPM-o：{answer}", flush=True)
        if result.get("answer_wav"):
            node.publish_wav(result["answer_wav"])
    node = RosPerceptionInput(handle)
    node.get_logger().info("Agent 已启动：订阅树莓派音视频，并回传模型语音")
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
