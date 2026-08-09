# 架构与模块

## 边界

```text
ROS topic / parameter
        │
robot_host/ros                 ROS 适配与进程启动
        │ C++ API
robot_host/core                可独立测试的上位机业务库
        │ USART3 二进制协议
small_car_f407                 实时控制与传感器采集

ros_middleware                公共 msg 和 ROS 2 容器环境
```

- `robot_host` 拥有上位机业务、ROS 节点、launch 和机器人参数。
- `ros_middleware` 只提供公共接口包与运行环境，不放机器人业务节点。
- 模块之间通过 ROS 串联；树莓派与 MCU 直接使用串口，不增加 IPC 或桥接进程。

## 核心模块

| 目录 | 职责 |
| --- | --- |
| `core/small_car_base/transport` | 串口打开、读写和恢复 |
| `core/small_car_base/protocol` | 帧、CRC、编解码和流解析 |
| `core/small_car_base/mcu` | 面向业务的 MCU 客户端 |
| `core/small_car_base/control` | 速度限幅、超时停车等安全逻辑 |
| `core/small_car_base/chassis` | YAML 参数加载、下发和回读校验 |
| `core/small_car_base/servo` | 云台角度与脉宽换算 |
| `core/small_car_base/audio` | ALSA 采集与播放能力 |
| `core/small_car_base/buffer` | 不依赖 ROS 的固定容量环形缓冲基础工具 |

## ROS 包

| 包 | 作用 |
| --- | --- |
| `small_car_base` | 串口底盘节点、里程计、IMU、超声、诊断和 EKF |
| `agent_client` | 摄像头启动、VAD/媒体缓冲、统一 Agent Action Client 和音频播放 |
| `small_car_description` | URDF、TF、RViz 配置 |
| `small_car_nav2` | Nav2 启动和参数 |
| `small_car_interfaces` | 公共全模态 Agent Action 和业务消息；位于 `ros_middleware/src` |

## 运行链路

控制链路：`Nav2/Agent -> /cmd_vel -> small_car_base -> USART3 -> MCU`。

状态链路：`MCU -> USART3 -> /wheel/odom_raw + /imu/data_raw -> EKF -> /odom`。

Agent 链路：`agent_client` 通过 `core/audio` 直接读写 ALSA，在进程内完成 VAD、预录和 WAV
缓冲；压缩相机消息只保留最新帧。两类媒体组成 `/car/agent/run` Goal，结果中的 WAV 直接播放，不建立逐帧音频 Topic。

缓冲生命周期由 `agent_client` 管理，`core` 只提供通用环形缓冲和设备读写原语。这样既避免硬件逻辑进入
ROS 业务层，也为后续 VLA 客户端复用同一 Action/媒体所有权模型保留扩展点。
