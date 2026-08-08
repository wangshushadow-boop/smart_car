# ROS 接口契约

共享接口定义位于 `src/small_car_interfaces`。发布者和订阅者的业务实现分别保留在 `robot_host`、`llm_agent` 等所属工程。

`src/small_car_interfaces/config/interfaces.yaml` 是 topic 名、消息类型和 QoS 的唯一事实源；它会随 `small_car_interfaces` 安装。树莓派 launch 与 WSL Agent 都直接读取该文件，禁止在两端重复硬编码跨工程 topic 名。

## Topic

| 名称 | 类型 | 约定 |
| --- | --- | --- |
| `/car/audio/input` | `small_car_interfaces/msg/AudioFrame` | 麦克风 PCM 音频帧 |
| `/car/audio/output` | `small_car_interfaces/msg/AudioFrame` | Agent 发送至车载扬声器的 PCM 音频帧 |
| `/car/camera/image/compressed` | `sensor_msgs/msg/CompressedImage` | 压缩相机图像 |

新增接口时优先使用 ROS 标准消息。新增或修改接口时，先更新 YAML，再更新本表中单位、坐标系、QoS、频率和超时语义。
