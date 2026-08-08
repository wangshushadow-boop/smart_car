# 底盘标定

标定时架空车轮或留出安全场地，限制速度并准备断电。一次只调整一类参数，确认后写回 `robot_host/ros/small_car_base/config/chassis.yaml`。

## 顺序

1. 检查电机方向和编码器正负。
2. 标定最小起步 PWM。
3. 标定左右输出一致性。
4. 标定直线里程比例。
5. 标定有效轮距。
6. 静态标定 IMU 安装偏置。
7. 最后调整轮速 PI 和 Nav2 参数。

## 准备

```bash
source /opt/ros/kilted/setup.bash
source robot_host/install-ros/setup.bash
ros2 topic echo /diagnostics --once
```

先保存原配置：

```bash
cp robot_host/ros/small_car_base/config/chassis.yaml /tmp/chassis.yaml.bak
```

## 标定脚本

查看脚本参数：

```bash
python3 robot_host/scripts/calibrate_wheel_pwm.py --help
python3 robot_host/scripts/calibrate_wheel_balance.py --help
python3 robot_host/scripts/calibrate_imu_static.py --help
python3 robot_host/scripts/trace_velocity_chain.py --help
```

- `calibrate_wheel_pwm.py`：寻找直行和原地转向的最小可靠 PWM。
- `calibrate_wheel_balance.py`：按编码器结果计算左右输出修正。
- `calibrate_imu_static.py`：采集静止 IMU，计算横滚/俯仰偏置和方差。
- `trace_velocity_chain.py`：对照 `/cmd_vel`、里程计和 MCU 诊断检查整条速度链路。

## 在线调整

```bash
ros2 param get /small_car_base wheel_pwm_min
ros2 param set /small_car_base wheel_pwm_min 580
```

节点会通过串口写入 MCU 并回读确认。在线值只用于试验；容器重启后以 `chassis.yaml` 为准。

## 里程与轮距

直线行驶已知距离后：

```text
new_odom_mm_per_tick_num = old_value × actual_distance / reported_distance
```

原地旋转已知角度后：

```text
new_wheel_track_mm = old_value × reported_yaw / actual_yaw
```

每次修正后至少重复三次双向测试，避免地面打滑造成单次误差。

## 验收

- 低速起步无长时间堵转，停车后不爬行。
- 前进与后退时里程计方向正确。
- 1 m 直线和 360° 原地旋转重复误差可接受。
- 静止 `/odom` 不持续漂移，`/diagnostics` 无串口或传感器错误。
- 最终 YAML 与实际运行参数一致并提交 Git。
