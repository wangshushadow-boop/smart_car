# 重构迁移说明

本文仅用于识别旧名称，新代码和其他文档不得继续使用旧接口。

| 旧项 | 当前实现 |
| --- | --- |
| 旧 ROS 工作区的 `ros2_ws/src` | `robot_host/ros` 与 `ros_middleware/src` |
| `smallcar_ros_and_mcu_bridge` | `small_car_base` |
| `small_car_motion_controller` | Nav2 标准 Controller/Behavior |
| 多个自研 ROS 底盘进程 | 单一 `small_car_base_node` |
| `/cmd_vel` `Twist` | `/cmd_vel` `TwistStamped` |
| `/cmd_vel_mcu`、`/control/source` | 删除，改为进程内调用 |
| `/debug/imu/raw` | `/imu/data_raw` |
| `/imu/data`、`/reset_odometry` | 删除，融合输出统一为 `/odom` |
| `left_servo_joint`、`right_servo_joint` | `upper_servo_joint`、`lower_servo_joint` |
| MCU odom | 累计编码器与原始 IMU，由上位机换算和融合 |

当前统一启动入口：

```bash
ros2 launch small_car_nav2 system.launch.py
```
