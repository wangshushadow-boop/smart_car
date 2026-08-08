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

## ROS 包

| 包 | 作用 |
| --- | --- |
| `small_car_base` | 串口底盘节点、里程计、IMU、超声、诊断和 EKF |
| `small_car_av` | 摄像头、压缩图像、音频输入与播放 |
| `small_car_description` | URDF、TF、RViz 配置 |
| `small_car_nav2` | Nav2 启动和参数 |
| `small_car_interfaces` | 公共 `AudioFrame`、`SpeechEvent` 消息；位于 `ros_middleware/src` |

## 运行链路

控制链路：`Nav2/Agent -> /cmd_vel -> small_car_base -> USART3 -> MCU`。

状态链路：`MCU -> USART3 -> /wheel/odom_raw + /imu/data_raw -> EKF -> /odom`。

音视频链路：设备由 `small_car_av` 直接访问并发布 ROS topic；音频底层复用 `core/audio`，没有重复的设备实现。
