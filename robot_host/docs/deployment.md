# 部署与运维

## 前置条件

树莓派需要：Docker、Docker Compose、CMake、可用的 MCU 串口、声卡和摄像头。默认设备为：

```text
/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C2C059301-if00
/dev/snd
/dev/video0
```

先检查：

```bash
test -e /dev/serial/by-id/usb-1a86_USB_Single_Serial_5C2C059301-if00
test -e /dev/snd
test -e /dev/video0
```

设备路径变化时，修改 `ros_middleware/docker/compose.yaml` 和 `robot_host/ros/small_car_av/launch/pi_av.launch.py`。

## 一键刷新

在 Windows 仓库根目录执行：

```powershell
.\robot_host\scripts\sync_ros2_host.ps1
```

自定义连接参数：

```powershell
.\robot_host\scripts\sync_ros2_host.ps1 `
  -HostAddress 192.168.3.85 `
  -UserName ubuntu `
  -RemoteWorkspace /home/ubuntu/small_car_f407
```

脚本会上传 `robot_host` 与 `ros_middleware`、编译并测试核心库、重建 ROS 工作区、启动容器，并检查 `/small_car_base` 和 `/car/audio/input`。

## 手动启动

```bash
cd ~/small_car_f407/ros_middleware/docker
docker compose up --build -d --force-recreate
docker compose ps
docker compose logs -f --tail=100
```

停止或重启：

```bash
docker compose down
docker compose restart small_car_ros2
```

## 运行检查

```bash
cd ~/small_car_f407/ros_middleware/docker
docker compose exec small_car_ros2 bash -lc '
  source /opt/ros/kilted/setup.bash
  source /workspace/smart_car/robot_host/install-ros/setup.bash
  ros2 node list
  ros2 topic list
  ros2 topic hz /wheel/odom_raw
  ros2 topic hz /car/audio/input
  ros2 topic echo /diagnostics --once
'
```

低速运动测试前先架空车轮并准备断电：

```bash
cd ~/small_car_f407/ros_middleware/docker
docker compose exec small_car_ros2 bash -lc '
  source /opt/ros/kilted/setup.bash
  source /workspace/smart_car/robot_host/install-ros/setup.bash
  ros2 topic pub --once /cmd_vel geometry_msgs/msg/TwistStamped \
    "{twist: {linear: {x: 0.1}, angular: {z: 0.0}}}"
'
```

节点在 500 ms 未收到有效命令后停车；MCU 另有 300 ms 主机命令看门狗。

## 常见问题

串口不存在：

```bash
ls -l /dev/serial/by-id/
cd ~/small_car_f407
sudo ./robot_host/tools/recover_mcu_usb.sh
```

ROS 构建目录由容器 root 创建而无法清理时：

```bash
cd ~/small_car_f407
docker run --rm -v "$PWD/robot_host:/target" small-car-ros2:kilted \
  bash -lc 'rm -rf /target/build-ros /target/install-ros /target/log-ros'
```

音视频设备检查：

```bash
arecord -l
aplay -l
v4l2-ctl --list-devices
```

配置入口：底盘节点参数在 `robot_host/ros/small_car_base/config/base.yaml`，MCU 标定参数在 `chassis.yaml`，导航参数在 `robot_host/ros/small_car_nav2/config/nav2.yaml`。
