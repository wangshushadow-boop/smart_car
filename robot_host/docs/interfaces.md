# ROS 接口

所有接口默认位于根命名空间。实际 topic 名、类型和 QoS 以
`ros_middleware/src/small_car_interfaces/config/interfaces.yaml` 为准；节点和
Agent 都直接读取该文件，不在实现中硬编码跨模块 topic 名。

## Topic

| 方向 | Topic | 类型 | 说明 |
| --- | --- | --- | --- |
| 输入 | `/cmd_vel` | `geometry_msgs/msg/TwistStamped` | `linear.x` m/s，`angular.z` rad/s |
| 输入 | `/servo_controller/joint_trajectory` | `trajectory_msgs/msg/JointTrajectory` | 云台关节目标 |
| 输入 | `/car/audio/output` | `small_car_interfaces/msg/AudioFrame` | PCM 播放数据，Reliable QoS |
| 输出 | `/wheel/odom_raw` | `nav_msgs/msg/Odometry` | 未融合轮式里程计 |
| 输出 | `/imu/data_raw` | `sensor_msgs/msg/Imu` | MCU 原始 IMU 换算值 |
| 输出 | `/odom` | `nav_msgs/msg/Odometry` | EKF 融合结果 |
| 输出 | `/ultrasonic/front` | `sensor_msgs/msg/Range` | 前向超声距离 |
| 输出 | `/joint_states` | `sensor_msgs/msg/JointState` | 四轮与云台关节状态 |
| 输出 | `/diagnostics` | `diagnostic_msgs/msg/DiagnosticArray` | 串口、MCU 和传感器状态 |
| 输出 | `/car/camera/image_raw` | `sensor_msgs/msg/Image` | 640×480 RGB8 原始图像 |
| 输出 | `/car/camera/camera_info` | `sensor_msgs/msg/CameraInfo` | 相机信息 |
| 输出 | `/car/camera/image/compressed` | `sensor_msgs/msg/CompressedImage` | JPEG 压缩图像 |
| 输出 | `/car/audio/input` | `small_car_interfaces/msg/AudioFrame` | 默认 16 kHz、单声道、PCM S16LE |

当前没有自定义 service 或 action。Nav2 使用其标准 action、service 和 lifecycle 接口。

## 音频消息

`AudioFrame`：

| 字段 | 含义 |
| --- | --- |
| `header` | 首个采样点的时间与来源 |
| `sample_rate` | 采样率，Hz |
| `channels` | 声道数 |
| `encoding` | 当前支持 `pcm_s16le` |
| `frame_samples` | 每声道采样点数 |
| `data` | 按声道交错的 PCM 字节 |

有效数据长度必须等于 `frame_samples × channels × 2`。

## 坐标系

```text
odom -> base_link -> imu_link
                  -> ultrasonic_link
                  -> wheel_*_link
                  -> servo links
```

`small_car_base` 发布动态 `odom -> base_link`，`robot_state_publisher` 发布 URDF 静态/关节 TF。当前没有 `map -> odom` 定位链路。

## 参数

节点参数位于 `robot_host/ros/small_car_base/config/base.yaml`，包括串口、超时、坐标系、传感器方差和舵机换算。可在线查看：

```bash
ros2 param list /small_car_base
ros2 param get /small_car_base cmd_vel_timeout_ms
```

MCU 的 24 个运行参数由 `chassis.yaml` 启动时逐项下发并回读，完整编号见 [串口协议](protocol.md#运行参数编号)。

## 快速验证

```bash
ros2 topic info /cmd_vel -v
ros2 topic echo /odom --once
ros2 topic echo /imu/data_raw --once
ros2 topic echo /diagnostics --once
ros2 topic hz /car/audio/input
ros2 run tf2_ros tf2_echo odom base_link
```
