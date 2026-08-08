# 树莓派运维

默认树莓派为 `ubuntu@192.168.3.85`，项目目录为
`~/small_car_f407/robot_host`。首次部署见[部署文档](docs/deployment.md)。

## 容器管理

```bash
ssh ubuntu@192.168.3.85
cd ~/small_car_f407/ros_middleware/docker
docker compose ps
docker compose logs -f small_car_ros2
docker compose restart small_car_ros2
```

修改 ROS 源码、launch 或 YAML 后重建并启动：

```bash
docker compose up --build -d --force-recreate
```

进入容器：

```bash
docker compose exec small_car_ros2 bash
source /opt/ros/kilted/setup.bash
source /workspace/smart_car/robot_host/install-ros/setup.bash
```

容器使用 `ROS_DOMAIN_ID=0` 和 Cyclone DDS；运行检查命令前，应保持该环境一致。

## ROS 状态检查

在容器内执行：

```bash
ros2 node list
ros2 topic echo /wheel/odom_raw --once
ros2 topic echo /imu/data_raw --once
ros2 topic echo /odom --once
ros2 topic echo /diagnostics --once
ros2 run tf2_ros tf2_echo odom base_link
ros2 lifecycle get /controller_server
```

当前音视频采集的节点为 `/car_camera`、`/car_image_republisher` 与
`/car_jabra_audio`；对外话题为 `/car/camera/image/compressed`、
`/car/camera/camera_info` 和 `/car/audio/input`。

## 低速运动测试

先架空车轮或确认前方安全。持续前进，按 `Ctrl+C` 结束：

```bash
ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/TwistStamped \
  "{header: auto, twist: {linear: {x: 0.1}, angular: {z: 0.0}}}"
```

停车：

```bash
ros2 topic pub --once /cmd_vel geometry_msgs/msg/TwistStamped \
  "{header: auto, twist: {linear: {x: 0.0}, angular: {z: 0.0}}}"
```

## 参数

| 文件 | 内容 |
| --- | --- |
| `robot_host/ros/small_car_base/config/chassis.yaml` | 轮距、编码器比例、轮速闭环和安全限制 |
| `robot_host/ros/small_car_base/config/base.yaml` | 串口、发布频率、坐标系和协方差 |
| `robot_host/ros/small_car_base/config/ekf.yaml` | 轮速与 IMU 融合 |
| `robot_host/ros/small_car_nav2/config/nav2.yaml` | Nav2 参数 |

在线调整示例：

```bash
ros2 param get /small_car_base wheel_pwm_min
ros2 param set /small_car_base wheel_pwm_min 550
```

在线修改不会写回 YAML；要持久化时修改文件后执行“容器管理”中的重建命令。

## MCU USB 恢复

```bash
sudo install -m 0644 systemd/small-car-mcu-recovery.path /etc/systemd/system/
sudo install -m 0644 systemd/small-car-mcu-recovery.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now small-car-mcu-recovery.path
journalctl -u small-car-mcu-recovery.service -f
```

相机、麦克风、ST-LINK 和串口连接见[硬件文档](hardware.md)。
