# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 仓库概览

`smart_car` 是一个多组件智能小车工程，三大子模块分别承担不同职责：

| 子目录 | 角色 | 平台 |
| --- | --- | --- |
| [`small_car_f407/`](small_car_f407/) | STM32F407 固件（电机闭环、传感器采集、串口协议、底盘安全） | Bare-metal / FreeRTOS |
| [`robot_host/`](robot_host/) | 树莓派上位机（ROS 2 / Nav2、URDF、MCU 协议桥、摄像头与 Jabra 麦克风采集） | Linux / WSL，ROS 2 Kilted |
| [`llm_agent/`](llm_agent/) | WSL 中的本地大模型服务（MiniCPM-o 4.5 AWQ + vLLM） | WSL2 Ubuntu 24.04 |

完整工作区规则参见 [`AGENTS.md`](AGENTS.md)；各子模块的细节分别见
[`small_car_f407/CLAUDE.md`](small_car_f407/CLAUDE.md) 以及
[`robot_host/README.md`](robot_host/README.md) / [`llm_agent/README.md`](llm_agent/README.md)。
修改协议或新增 topic 时必须同时检查 `small_car_f407/Core/Modules/Comm/` 与
`robot_host/src/small_car_base/protocol/` 的两端实现。

## 常用命令

```powershell
# 固件（small_car_f407/，需要 ARM GCC + CMake 3.22+ + Ninja）
cmake --preset Debug
cmake --build --preset Debug

# 宿主机 C++ 工具与测试（robot_host/，Linux/WSL）
cmake -S . -B build && cmake --build build
ctest --test-dir build --output-on-failure

# ROS 2 工作区（robot_host/，已 source ROS 2 Kilted）
colcon build --symlink-install
colcon test --event-handlers console_direct+

# 容器化的硬件集成镜像（robot_host/）
docker compose -f ros2/compose.yaml up --build -d

# 树莓派一键同步与部署（PowerShell）
.\robot_host\scripts\sync_ros2_host.ps1

# WSL 大模型服务（llm_agent/，在 WSL Ubuntu-24.04 内）
./scripts/start_minicpm.sh
./scripts/status_minicpm.sh
./scripts/stop_minicpm.sh
```

固件使用 Google 风格 clang-format（2 空格、120 列），C 代码遵守 `.clang-format`；
Host 代码 C++17，使用 `UpperCamelCase` 类型/函数、`snake_case` 变量。
ROS / Python 代码遵循各包内的 `setup.py` 与 PEP 8 默认。

## 高层架构

控制流：`Nav2 Controller → /cmd_vel → small_car_base_node → MCU 串口 → 电机`。

- **底盘安全** 是最后一道防线，由 MCU 内的 `control_mux` 仲裁（安全 > 手柄 > 上位机 > 空闲），上位机和 Nav2 都无法绕过它。
- **MCU 不计算位姿**：底盘节点仅做编码器运动学换算和 IMU SI 单位转换；`robot_localization`（`ekf_filter_node`）融合轮速与 IMU，发布 `/odom`。
- **Nav2 容器化运行**，底盘/EKF/机器人模型节点独立运行避免重复。
- **音视频采集** 在 Nav2 容器中通过 `/dev/video0` 和 `/dev/snd` 直通设备，发布 `/car/camera/image/compressed`、`/car/camera/camera_info`、`/car/audio/input`。
- **大模型** 通过 OpenAI 兼容 API（`http://127.0.0.1:8000/v1`，模型 `minicpm-o-4.5-awq`）对外提供，独立于底盘与 ROS。

`protocol/transport/mcu/control/servo/ros` 的分层约束（详见
[`robot_host/docs/architecture.md`](robot_host/docs/architecture.md)）：

- `protocol` 不访问串口，`transport` 不解析协议；
- `mcu` 组合协议与传输，但不创建 ROS 接口；
- `control`、`servo` 使用 SI 单位且不依赖 ROS；
- 只有 `ros` 层负责 ROS 消息转换与调度；
- 同时刻仅允许一个进程占用 MCU 串口。

## 提交与文档约定

- Commit 主题使用简短中文祈使句（如 `优化底盘yaml参数`），每个 commit 只对应一个特性或修复，并在主题中点出模块或硬件接口。
- PR 需说明行为变更、验证命令与硬件测试、关联 issue，并显式标注 `.ioc`、协议、引脚、参数或 launch 文件的变更。
- 不提交构建产物、固件二进制、地图、日志或本地 IDE 配置（见 `.gitignore`）。
- 硬件原理图和接线长期资料放在 `small_car_f407/docs/`；树莓派设备操作放在 `robot_host/docs/deployment.md`。
- 修改 `small_car_f407.ioc` 后 CubeMX 会重新生成文件，自定义代码必须留在 `USER CODE BEGIN/END` 区块内，应用模块放在 `small_car_f407/Core/Modules/` 下，不受 CubeMX 管理。
- WSL 模型密钥、Agent 本地 `.env` 等敏感信息不得进入仓库；本地 `.env` 应加入 `.gitignore`。
