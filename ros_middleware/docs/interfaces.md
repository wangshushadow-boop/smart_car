# ROS 接口契约

共享接口定义位于 `src/small_car_interfaces`。发布者和订阅者的业务实现分别保留在 `robot_host`、`llm_agent` 等所属工程。

## Topic

| 名称 | 类型 | 约定 |
| --- | --- | --- |
| `/car/audio/input` | `small_car_interfaces/msg/AudioFrame` | 麦克风 PCM 音频帧 |
| `/car/agent/speech_finished` | `small_car_interfaces/msg/SpeechEvent` | 一轮语音输入结束事件 |
| `/car/camera/image/compressed` | `sensor_msgs/msg/CompressedImage` | 压缩相机图像 |

新增接口时优先使用 ROS 标准消息。自定义接口必须在这里记录单位、坐标系、QoS、频率和超时语义。
