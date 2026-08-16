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
ros2 topic echo /car/path --once
ros2 topic echo /ultrasonic/front --once
ros2 run tf2_ros tf2_echo odom base_link
ros2 lifecycle nodes
ros2 action info /drive_on_heading
ros2 action info /spin
```

速度链路：

```text
Nav2 controller -> cmd_vel_nav -> velocity_smoother -> /cmd_vel -> small_car_base -> MCU
```

局部和全局代价地图当前都读取 `/ultrasonic/front`。修改控制器、速度平滑器或代价地图参数时编辑 `robot_host/ros/small_car_nav2/config/nav2.yaml` 并重建 ROS 工作区。

## Agent 相对运动

树莓派语音请求的执行链路：

```text
用户“向前一米”
  -> Agent Server 白名单 Tool
  -> /car/agent/tool_execute
  -> robot_tool_gateway 严格校验距离/角度和并发状态
  -> /drive_on_heading 或 /spin
  -> Nav2 behavior_server + collision monitor
  -> /cmd_vel -> small_car_base -> MCU
```

本地限制位于 `small_car_interfaces/config/robot_tools.yaml`，Gateway 还在代码中执行同等边界校验。
模型不能指定速度、超时、关闭碰撞检查或直接发布 `/cmd_vel`。运动未结束时拒绝新运动；“停止”会取消当前 Nav2 Goal。

实车测试前架空车轮，并先确认 `/odom`、`odom -> base_link`、前向超声和急停均正常。可绕过 Agent
单独验证 Nav2：

```bash
ros2 action send_goal /drive_on_heading nav2_msgs/action/DriveOnHeading \
  "{target: {x: 0.2}, speed: 0.1, time_allowance: {sec: 5}, disable_collision_checks: false}"
```

## 当前限制

当前只有 `odom -> base_link`，没有地图、激光雷达或 `map -> odom` 定位。因此系统支持受限的相对
直线/旋转、底盘控制和局部避障验证，不具备可靠的全局定位与地图目标导航能力。

接入 SLAM 或定位后，需要增加传感器驱动、`map -> odom` 发布者和地图服务器，再启用全局目标导航。

## 故障定位

```bash
ros2 topic info /cmd_vel -v
ros2 topic echo /diagnostics --once
python3 robot_host/scripts/trace_velocity_chain.py --help
```

若 Nav2 正常但车辆不动，依次检查 `/cmd_vel` 是否有数据、消息时间戳是否新鲜、`/diagnostics` 中串口状态，以及 MCU 主机控制是否超时。
