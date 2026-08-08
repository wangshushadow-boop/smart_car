#!/usr/bin/env python3
"""短时发布速度并跟踪 Nav2 到底盘的三段速度链。"""

import argparse
import statistics
import time

import rclpy
from diagnostic_msgs.msg import DiagnosticArray
from geometry_msgs.msg import TwistStamped
from sensor_msgs.msg import JointState

from interface_contract import load_topics


def median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--linear", type=float, default=0.0)
    parser.add_argument("--angular", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--confirm-safe-test", action="store_true")
    args = parser.parse_args()
    if not args.confirm_safe_test:
        parser.error("必须使用 --confirm-safe-test 确认测试区域安全")

    rclpy.init()
    node = rclpy.create_node("velocity_chain_trace")
    topics = load_topics(
        "cmd_vel",
        "cmd_vel_nav",
        "cmd_vel_smoothed",
        "diagnostics",
        "joint_states",
    )
    # 与 Nav2 Velocity Smoother 的 KEEP_LAST(1) 输入保持完全一致。
    publisher = node.create_publisher(TwistStamped, topics["cmd_vel_nav"], 1)
    smoothed_linear: list[float] = []
    smoothed_angular: list[float] = []
    output_linear: list[float] = []
    output_angular: list[float] = []
    left_speed: list[float] = []
    right_speed: list[float] = []
    controller_values: dict[str, str] = {}

    def on_smoothed(message: TwistStamped) -> None:
        smoothed_linear.append(message.twist.linear.x)
        smoothed_angular.append(message.twist.angular.z)

    def on_output(message: TwistStamped) -> None:
        output_linear.append(message.twist.linear.x)
        output_angular.append(message.twist.angular.z)

    node.create_subscription(
        TwistStamped, topics["cmd_vel_smoothed"], on_smoothed, 20
    )
    node.create_subscription(TwistStamped, topics["cmd_vel"], on_output, 20)

    def on_joint_state(message: JointState) -> None:
        if len(message.velocity) >= 4:
            left_speed.append((message.velocity[0] + message.velocity[1]) / 2.0)
            right_speed.append((message.velocity[2] + message.velocity[3]) / 2.0)

    def on_diagnostics(message: DiagnosticArray) -> None:
        for status in message.status:
            if status.name == "small_car/controller":
                controller_values.clear()
                controller_values.update({item.key: item.value for item in status.values})

    node.create_subscription(JointState, topics["joint_states"], on_joint_state, 20)
    node.create_subscription(DiagnosticArray, topics["diagnostics"], on_diagnostics, 20)

    match_deadline = time.monotonic() + 15.0
    while rclpy.ok() and publisher.get_subscription_count() < 1:
        if time.monotonic() >= match_deadline:
            raise RuntimeError("15 秒内未发现导航速度输入订阅者")
        rclpy.spin_once(node, timeout_sec=0.1)
    print(f"已匹配导航速度输入订阅者: {publisher.get_subscription_count()}")

    def publish_for(linear: float, angular: float, duration: float) -> None:
        end = time.monotonic() + duration
        while rclpy.ok() and time.monotonic() < end:
            message = TwistStamped()
            message.header.stamp = node.get_clock().now().to_msg()
            message.twist.linear.x = linear
            message.twist.angular.z = angular
            publisher.publish(message)
            rclpy.spin_once(node, timeout_sec=0.05)

    publish_for(0.0, 0.0, 2.0)
    smoothed_linear.clear()
    smoothed_angular.clear()
    output_linear.clear()
    output_angular.clear()
    left_speed.clear()
    right_speed.clear()
    publish_for(args.linear, args.angular, args.duration)
    print(f"目标速度: linear={args.linear:.3f} m/s, angular={args.angular:.3f} rad/s")
    print(
        f"平滑输出中值: linear={median_or_none(smoothed_linear)}, "
        f"angular={median_or_none(smoothed_angular)}, 样本={len(smoothed_linear)}"
    )
    print(
        f"碰撞监控输出中值: linear={median_or_none(output_linear)}, "
        f"angular={median_or_none(output_angular)}, 样本={len(output_linear)}"
    )
    print(
        f"左/右轮速度中值: {median_or_none(left_speed)} / "
        f"{median_or_none(right_speed)} rad/s, 样本={len(left_speed)}"
    )
    print(f"MCU 状态: {controller_values}")
    publish_for(0.0, 0.0, 1.0)
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
