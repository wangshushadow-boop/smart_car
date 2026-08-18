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

设备路径变化时，修改 `ros_middleware/docker/compose.yaml` 和
`robot_host/ros/agent_client/config/agent_client.yaml`；摄像头参数位于
`robot_host/ros/agent_client/launch/agent_client.launch.py`。

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
  -RemoteWorkspace /home/ubuntu/smart_car
```

脚本会上传 `robot_host` 与 `ros_middleware`、编译并测试核心库、清理旧容器和 ROS 安装空间、
以单实例启动容器，并检查节点无重名、`/car/agent/tool_execute` 恰好有一个 Server、Nav2 生命周期
全部激活以及相机 Topic 可用。任一检查失败都会输出容器末尾日志并让部署失败。

## 手动启动

```bash
cd ~/smart_car/ros_middleware/docker
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
cd ~/smart_car/ros_middleware/docker
docker compose exec small_car_ros2 bash -lc '
  source /opt/ros/kilted/setup.bash
  source /workspace/smart_car/robot_host/install-ros/setup.bash
  ros2 node list
  ros2 topic list
  ros2 topic hz /wheel/odom_raw
  ros2 node info /car_agent_client
  ros2 topic hz /car/camera/image/compressed
  ros2 service type /car/agent/run
  ros2 action info /car/agent/tool_execute
  ros2 topic echo /diagnostics --once
'
```

也可以直接运行与一键部署相同的完整健康检查：

```bash
docker compose exec small_car_ros2 \
  bash /workspace/smart_car/robot_host/scripts/verify_ros_runtime.sh
```

低速运动测试前先架空车轮并准备断电：

```bash
cd ~/smart_car/ros_middleware/docker
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
cd ~/smart_car
sudo ./robot_host/tools/recover_mcu_usb.sh
```

ROS 构建目录由容器 root 创建而无法清理时：

```bash
cd ~/smart_car
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
