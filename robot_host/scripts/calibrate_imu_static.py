#!/usr/bin/env python3
"""采集静止 IMU 数据，计算均值、噪声和建议 ROS 协方差。"""

import math
import statistics
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Imu

from interface_contract import load_topics


def main() -> int:
    rclpy.init()
    node = rclpy.create_node("imu_static_calibration")
    topics = load_topics("imu_data_raw")
    samples: list[tuple[float, float, float, float, float, float]] = []

    def callback(message: Imu) -> None:
        samples.append(
            (
                message.linear_acceleration.x,
                message.linear_acceleration.y,
                message.linear_acceleration.z,
                message.angular_velocity.x,
                message.angular_velocity.y,
                message.angular_velocity.z,
            )
        )

    node.create_subscription(Imu, topics["imu_data_raw"], callback, qos_profile_sensor_data)
    end = time.monotonic() + 20.0
    while rclpy.ok() and time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0.1)

    if len(samples) < 200:
        raise RuntimeError(f"IMU 样本不足: {len(samples)}")

    columns = list(zip(*samples))
    means = [statistics.mean(column) for column in columns]
    variances = [statistics.pvariance(column) for column in columns]
    acceleration_variance = max(0.001, max(variances[:3]) * 4.0)
    # 当前 EKF 只融合 Z 轴角速度；把静止偏差计入均方误差，避免过度信任 IMU。
    gyro_z_mse = variances[5] + means[5] * means[5]
    angular_velocity_variance = max(0.0001, gyro_z_mse * 4.0)

    gravity = math.sqrt(sum(value * value for value in means[:3]))
    print(f"样本数: {len(samples)}")
    print(
        "加速度均值 [m/s^2]: "
        f"x={means[0]:.6f}, y={means[1]:.6f}, z={means[2]:.6f}, |g|={gravity:.6f}"
    )
    print(
        "角速度均值 [rad/s]: "
        f"x={means[3]:.6f}, y={means[4]:.6f}, z={means[5]:.6f}"
    )
    print(
        "加速度方差: " + ", ".join(f"{value:.8f}" for value in variances[:3])
    )
    print(
        "角速度方差: " + ", ".join(f"{value:.8f}" for value in variances[3:])
    )
    print(f"建议 imu_acceleration_variance={acceleration_variance:.6f}")
    print(f"建议 imu_angular_velocity_variance={angular_velocity_variance:.6f}")

    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
