# 树莓派上位机

`robot_host` 是完整的上位机工程：它包含不依赖 ROS 的硬件核心、上位机 ROS 业务节点、系统启动文件以及部署和运维工具。

## 目录

| 路径 | 内容 |
| --- | --- |
| `core/small_car_base` | MCU 协议、串口、底盘安全、参数、舵机和流式 ALSA 音频等纯 C++ 实现 |
| `ros/small_car_base` | MCU 硬件节点、EKF、参数和基础启动入口 |
| `ros/small_car_av` | 摄像头节点及复用核心 ALSA 库的 Jabra C++ 音频节点 |
| `ros/small_car_description` | URDF、RViz 和固定 TF |
| `ros/small_car_nav2` | Nav2 参数与整机启动入口 |
| `scripts`、`tools`、`systemd` | 标定、OTA、恢复和部署工具 |

共享 ROS 消息、DDS 配置和容器环境位于相邻的 `ros_middleware` 工程。上位机节点直接调用 `core` 并访问串口，不经过 IPC 或额外桥接进程。

## 构建核心模块

```bash
cmake -S robot_host -B robot_host/build-host
cmake --build robot_host/build-host
ctest --test-dir robot_host/build-host --output-on-failure
```

## 启动完整 ROS 系统

```bash
docker compose -f ros_middleware/docker/compose.yaml up --build -d
```

容器同时构建 `ros_middleware/src` 和 `robot_host/ros`，随后启动 `small_car_av` 与 `small_car_nav2/system.launch.py`。
