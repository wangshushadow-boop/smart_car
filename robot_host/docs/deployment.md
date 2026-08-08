# 树莓派部署

## 环境

- 上位机：`ubuntu@192.168.3.85`，Raspberry Pi 5/aarch64。
- 部署目录：`~/small_car_f407/robot_host`。
- 容器：ROS 2 Kilted，镜像 `small-car-ros2:kilted`。
- MCU 容器设备：`/dev/small_car_mcu`。

Windows 需要 `tar`、`scp`、`ssh`；树莓派需要 Docker、Compose 和 CMake。

## 一键部署

```powershell
.\robot_host\scripts\sync_ros2_host.ps1
```

脚本依次打包并上传源码、替换板端目录、构建宿主机工具、运行 CTest，然后执行：

```bash
docker compose up --build -d --force-recreate
```

`--build` 会检查 Dockerfile。缓存命中时依赖层显示 `CACHED`；Dockerfile、基础镜像或构建缓存变化时会重新下载 APT/pip 依赖。

## 验收

```bash
ssh ubuntu@192.168.3.85
cd ~/small_car_f407/ros_middleware/docker
docker compose ps
docker compose logs -f small_car_ros2
```

正常日志包含：

```text
applied and verified 24 chassis parameters
small car base ready: /dev/small_car_mcu @ 115200
Managed nodes are active
```

进入容器检查数据链：

```bash
docker compose exec small_car_ros2 bash
source /opt/ros/kilted/setup.bash
source /workspace/smart_car/robot_host/install-ros/setup.bash
ros2 topic echo /wheel/odom_raw --once
ros2 topic echo /imu/data_raw --once
ros2 topic echo /odom --once
ros2 run tf2_ros tf2_echo odom base_link
```

镜像构建中断且容器已停止时，可执行 `docker compose up -d` 恢复现有镜像。
