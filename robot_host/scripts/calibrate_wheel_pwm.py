#!/usr/bin/env python3
"""在四轮架空状态下自动搜索轮组可靠起转所需的最小 PWM。"""

import argparse
import math
import statistics
import time

import rclpy
from geometry_msgs.msg import TwistStamped
from nav2_msgs.srv import ManageLifecycleNodes
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import GetParameters, SetParameters
from sensor_msgs.msg import JointState

from interface_contract import load_topics


class WheelPwmCalibration:
    def __init__(self) -> None:
        self.node = rclpy.create_node("wheel_pwm_calibration")
        topics = load_topics("cmd_vel", "joint_states")
        self.publisher = self.node.create_publisher(
            TwistStamped, topics["cmd_vel"], 10
        )
        self.node.create_subscription(
            JointState, topics["joint_states"], self._on_joint_state, 20
        )
        self.set_client = self.node.create_client(
            SetParameters, "/small_car_base/set_parameters"
        )
        self.get_client = self.node.create_client(
            GetParameters, "/small_car_base/get_parameters"
        )
        self.nav_client = self.node.create_client(
            ManageLifecycleNodes,
            "/lifecycle_manager_navigation/manage_nodes",
        )
        self.samples: list[tuple[float, float, float]] = []

    def _on_joint_state(self, message: JointState) -> None:
        if len(message.velocity) < 4:
            return
        left = (message.velocity[0] + message.velocity[1]) / 2.0
        right = (message.velocity[2] + message.velocity[3]) / 2.0
        self.samples.append((time.monotonic(), left, right))

    def wait_for_services(self) -> None:
        if not self.set_client.wait_for_service(timeout_sec=15.0):
            raise RuntimeError("找不到 /small_car_base/set_parameters")
        if not self.get_client.wait_for_service(timeout_sec=15.0):
            raise RuntimeError("找不到 /small_car_base/get_parameters")
        if not self.nav_client.wait_for_service(timeout_sec=15.0):
            raise RuntimeError("找不到 Nav2 生命周期管理服务")

    def manage_nav(self, command: int) -> None:
        request = ManageLifecycleNodes.Request(command=command)
        future = self.nav_client.call_async(request)
        rclpy.spin_until_future_complete(self.node, future, timeout_sec=20.0)
        if not future.done() or future.result() is None:
            raise RuntimeError("Nav2 生命周期操作超时")
        if not future.result().success:
            raise RuntimeError("Nav2 生命周期操作失败")

    def get_pwm(self) -> int:
        request = GetParameters.Request(names=["wheel_pwm_min"])
        future = self.get_client.call_async(request)
        rclpy.spin_until_future_complete(self.node, future, timeout_sec=10.0)
        if not future.done() or future.result() is None:
            raise RuntimeError("读取 wheel_pwm_min 超时")
        return int(future.result().values[0].integer_value)

    def set_pwm(self, pwm: int) -> None:
        request = SetParameters.Request(
            parameters=[
                Parameter(
                    name="wheel_pwm_min",
                    value=ParameterValue(
                        type=ParameterType.PARAMETER_INTEGER,
                        integer_value=pwm,
                    ),
                )
            ]
        )
        future = self.set_client.call_async(request)
        rclpy.spin_until_future_complete(self.node, future, timeout_sec=10.0)
        if not future.done() or future.result() is None:
            raise RuntimeError(f"设置 wheel_pwm_min={pwm} 超时")
        result = future.result().results[0]
        if not result.successful:
            raise RuntimeError(f"设置 wheel_pwm_min={pwm} 失败: {result.reason}")

    def publish_for(self, linear_x: float, duration: float) -> None:
        end = time.monotonic() + duration
        while rclpy.ok() and time.monotonic() < end:
            message = TwistStamped()
            message.header.stamp = self.node.get_clock().now().to_msg()
            message.twist.linear.x = linear_x
            self.publisher.publish(message)
            rclpy.spin_once(self.node, timeout_sec=0.05)

    def stop(self) -> None:
        self.publish_for(0.0, 1.0)

    def test(self, pwm: int, direction: float) -> bool:
        self.stop()
        self.set_pwm(pwm)
        self.samples.clear()
        started_at = time.monotonic()
        self.publish_for(direction * 0.10, 4.5)
        relevant = [sample for sample in self.samples if sample[0] >= started_at]
        moving = [
            sample
            for sample in relevant
            if abs(sample[1]) >= 1.0 and abs(sample[2]) >= 1.0
        ]
        onset = moving[0][0] - started_at if moving else math.inf
        tail = [sample for sample in relevant if sample[0] - started_at >= 2.0]
        stable_ratio = (
            sum(abs(sample[1]) >= 1.0 and abs(sample[2]) >= 1.0 for sample in tail)
            / len(tail)
            if tail
            else 0.0
        )
        left_median = statistics.median(abs(sample[1]) for sample in tail) if tail else 0.0
        right_median = statistics.median(abs(sample[2]) for sample in tail) if tail else 0.0
        passed = onset <= 1.5 and stable_ratio >= 0.85
        label = "前进" if direction > 0 else "后退"
        onset_text = f"{onset:.2f}s" if math.isfinite(onset) else "未起转"
        print(
            f"{label} PWM={pwm}: {'通过' if passed else '失败'}, "
            f"起转={onset_text}, 稳定率={stable_ratio:.0%}, "
            f"左右轮={left_median:.2f}/{right_median:.2f} rad/s",
            flush=True,
        )
        self.stop()
        return passed

    def search(self, direction: float, lower: int, upper: int) -> int:
        if self.test(lower, direction):
            return lower
        if not self.test(upper, direction):
            raise RuntimeError(f"PWM={upper} 仍无法可靠起转，请检查供电和机械阻力")
        failed = lower
        passed = upper
        while passed - failed > 10:
            middle = ((failed + passed) // 20) * 10
            middle = max(failed + 10, min(middle, passed - 10))
            if self.test(middle, direction):
                passed = middle
            else:
                failed = middle
        return passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-wheels-off-ground",
        action="store_true",
        help="确认四轮已架空；未指定时拒绝驱动",
    )
    args = parser.parse_args()
    if not args.confirm_wheels_off_ground:
        parser.error("必须使用 --confirm-wheels-off-ground 确认四轮架空")

    rclpy.init()
    calibration = WheelPwmCalibration()
    original_pwm = 550
    nav_paused = False
    try:
        calibration.wait_for_services()
        original_pwm = calibration.get_pwm()
        print(f"原 wheel_pwm_min={original_pwm}", flush=True)
        calibration.manage_nav(1)
        nav_paused = True
        print("Nav2 已暂停，标定节点独占速度命令接口", flush=True)
        # 先用零速度完成 DDS 匹配，避免把首次发现耗时计入电机起转时间。
        calibration.publish_for(0.0, 4.0)
        forward = calibration.search(1.0, 550, 1000)
        reverse = calibration.search(-1.0, 550, 1000)
        threshold = max(forward, reverse)
        recommended = min(1000, ((threshold + 29) // 10) * 10)
        print(
            f"搜索结果: 前进={forward}, 后退={reverse}, "
            f"架空建议值={recommended}",
            flush=True,
        )
        if not calibration.test(recommended, 1.0):
            raise RuntimeError("建议值前进复测失败")
        if not calibration.test(recommended, -1.0):
            raise RuntimeError("建议值后退复测失败")
        return 0
    finally:
        try:
            calibration.stop()
            calibration.set_pwm(original_pwm)
            print(f"已恢复 wheel_pwm_min={original_pwm}", flush=True)
        finally:
            if nav_paused:
                calibration.manage_nav(2)
                print("Nav2 已恢复", flush=True)
            calibration.node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
