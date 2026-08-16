# robot_host

树莓派上位机工程。业务能力放在 `core/`，ROS 2 适配、启动和参数放在 `ros/`；公共消息定义和容器环境位于仓库根目录的 `ros_middleware/`。

## 目录

```text
robot_host/
├── core/small_car_base/     # 与 ROS 无关的串口、协议、底盘、舵机和音频库
├── ros/                     # ROS 节点、launch、参数、URDF 和 Nav2
├── scripts/                 # 部署、标定和固件升级脚本
├── tools/                   # MCU OTA、USB 恢复及语音工具
├── systemd/                 # MCU USB 自动恢复服务
└── docs/                    # 操作文档
```

## 常用操作

本机编译和测试核心库：

```bash
cd robot_host
cmake -S . -B build-host
cmake --build build-host -j
ctest --test-dir build-host --output-on-failure
```

Windows 一键刷新树莓派环境：

```powershell
.\robot_host\scripts\sync_ros2_host.ps1
```

树莓派查看状态：

```bash
cd ~/smart_car/ros_middleware/docker
docker compose ps
docker compose logs -f --tail=100
```

## 文档导航

- [架构与模块](docs/architecture.md)：模块边界和数据链路
- [开发与测试](docs/development.md)：构建、测试和新增模块
- [部署与运维](docs/deployment.md)：树莓派刷新、启动、检查和故障处理
- [ROS 接口](docs/interfaces.md)：topic、消息、坐标系和参数
- [串口协议](docs/protocol.md)：完整帧格式、消息、参数和 OTA 子协议
- [底盘标定](docs/calibration.md)：标定顺序和脚本
- [固件升级](../small_car_f407/docs/firmware-update.md)：首次烧录和日常 OTA
- [导航操作](docs/navigation.md)：Nav2 启动、验证和当前限制

文档只描述当前有效方案；历史迁移过程以 Git 记录为准。
