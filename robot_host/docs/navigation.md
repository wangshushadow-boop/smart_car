# 导航操作

## 启动

容器默认同时启动底盘、机器人描述、EKF、音视频和 Nav2。单独启动导航系统：

```bash
source /opt/ros/kilted/setup.bash
source robot_host/install-ros/setup.bash
ros2 launch small_car_nav2 system.launch.py
```

指定参数文件：

```bash
ros2 launch small_car_nav2 system.launch.py \
  params_file:=/absolute/path/nav2.yaml
```

## 数据检查

```bash
ros2 topic hz /odom
ros2 topic echo /ultrasonic/front --once
ros2 run tf2_ros tf2_echo odom base_link
ros2 lifecycle nodes
```

速度链路：

```text
Nav2 controller -> cmd_vel_nav -> velocity_smoother -> /cmd_vel -> small_car_base -> MCU
```

局部和全局代价地图当前都读取 `/ultrasonic/front`。修改控制器、速度平滑器或代价地图参数时编辑 `robot_host/ros/small_car_nav2/config/nav2.yaml` 并重建 ROS 工作区。

## 当前限制

当前只有 `odom -> base_link`，没有地图、激光雷达或 `map -> odom` 定位。因此系统适合验证底盘控制、局部避障和 Nav2 链路，不具备可靠的全局定位与地图导航能力。

接入 SLAM 或定位后，需要增加传感器驱动、`map -> odom` 发布者和地图服务器，再启用全局目标导航。

## 故障定位

```bash
ros2 topic info /cmd_vel -v
ros2 topic echo /diagnostics --once
python3 robot_host/scripts/trace_velocity_chain.py --help
```

若 Nav2 正常但车辆不动，依次检查 `/cmd_vel` 是否有数据、消息时间戳是否新鲜、`/diagnostics` 中串口状态，以及 MCU 主机控制是否超时。
