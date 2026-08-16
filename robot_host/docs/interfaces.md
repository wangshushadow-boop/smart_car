# ROS 接口

所有接口默认位于根命名空间。实际 topic 名、类型和 QoS 以
`ros_middleware/src/small_car_interfaces/config/interfaces.yaml` 为准；节点和
Agent 都直接读取该文件，不在实现中硬编码跨模块 topic 名。

## Topic

| 方向 | Topic | 类型 | 说明 |
| --- | --- | --- | --- |
| 输入 | `/cmd_vel` | `geometry_msgs/msg/TwistStamped` | `linear.x` m/s，`angular.z` rad/s |
| 输入 | `/servo_controller/joint_trajectory` | `trajectory_msgs/msg/JointTrajectory` | 云台关节目标 |
| 输出 | `/wheel/odom_raw` | `nav_msgs/msg/Odometry` | 未融合轮式里程计 |
| 输出 | `/imu/data_raw` | `sensor_msgs/msg/Imu` | MCU 原始 IMU 换算值 |
| 输出 | `/odom` | `nav_msgs/msg/Odometry` | EKF 融合结果 |
| 输出 | `/car/path` | `nav_msgs/msg/Path` | 基于 `/odom` 累积的 RViz 调试轨迹 |
| 输出 | `/ultrasonic/front` | `sensor_msgs/msg/Range` | 前向超声距离 |
| 输出 | `/joint_states` | `sensor_msgs/msg/JointState` | 四轮与云台关节状态 |
| 输出 | `/diagnostics` | `diagnostic_msgs/msg/DiagnosticArray` | 串口、MCU 和传感器状态 |
| 输出 | `/car/camera/image_raw` | `sensor_msgs/msg/Image` | 640×480 RGB8 原始图像 |
| 输出 | `/car/camera/camera_info` | `sensor_msgs/msg/CameraInfo` | 相机信息 |
| 输出 | `/car/camera/image/compressed` | `sensor_msgs/msg/CompressedImage` | JPEG 压缩图像 |

## Agent Action

树莓派和 Web 使用同一个自定义 Action：

| Action | 类型 | 说明 |
| --- | --- | --- |
| `/car/agent/run` | `small_car_interfaces/action/RunAgent` | 统一文本、音频、图片、视频输入输出 |
| `/car/agent/tool_execute` | `small_car_interfaces/action/ExecuteRobotTool` | Agent Server 调用树莓派安全工具网关 |

## Agent Service

| Service | 类型 | 说明 |
| --- | --- | --- |
| `/car/audio/enqueue` | `small_car_interfaces/srv/PlayAudio` | Agent Server 提交最终 WAV；树莓派确认接收后后台播放，不等待播放结束 |

`agent_client/car_agent_client` 在树莓派侧把 VAD 完成的 WAV 和最近 JPEG 组成 Goal，并处理返回的
文字与状态。最终播报由独立 Service 主动下发；Web Debug 仍只使用统一 Action，因此调试代码不进入
Agent 或树莓派客户端。

## 树莓派音频数据路径

音频不再通过 ROS Topic 逐帧传输。`agent_client` 直接调用 `core/small_car_base/audio` 访问 ALSA：

- 空闲时只维护固定容量的预录环形缓冲；
- VAD 触发后直接写入 `agent_client` 自己预分配的 WAV 缓冲；
- 提交 Goal 时移动缓冲所有权，不在业务层复制整段语音；
- Agent Server 通过 `/car/audio/enqueue` Service 主动提交最终 WAV；Service
  确认播放器接收后立即返回，由 Agent Client 的后台线程直接交给 ALSA。

相机仍以 `sensor_msgs/msg/CompressedImage` 接入，客户端保存最新消息的所有权，并在组装 Goal 时移动 JPEG
字节。DDS 序列化/反序列化和跨机器网络传输产生的边界复制不可避免，但树莓派业务进程内不重复复制大媒体。

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
ros2 node info /car_agent_client
ros2 topic hz /car/camera/image/compressed
ros2 action info /car/agent/run
ros2 run tf2_ros tf2_echo odom base_link
```
