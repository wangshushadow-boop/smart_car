# ROS 接口契约

共享接口定义位于 `src/small_car_interfaces`。发布者和订阅者的业务实现分别保留在 `robot_host`、`llm_agent` 等所属工程。

`src/small_car_interfaces/config/interfaces.yaml` 是 topic 和 action 名称、消息类型及 QoS 的唯一事实源；
它会随 `small_car_interfaces` 安装。树莓派、WSL Agent 和 Web Debug 都读取该文件。

## Action

| 名称 | 类型 | 约定 |
| --- | --- | --- |
| `/car/agent/run` | `small_car_interfaces/action/RunAgent` | Web 和树莓派访问 Agent 的唯一全模态业务接口 |
| `/drive_on_heading` | `nav2_msgs/action/DriveOnHeading` | 树莓派执行受限的相对直线运动 |
| `/spin` | `nav2_msgs/action/Spin` | 树莓派执行受限的原地旋转 |

`/car/agent/run` 的 Goal 使用 `AgentRequest`，Feedback 使用 `AgentProgress`，Result 使用 `AgentResponse`。输入和输出均由
`AgentContent[]` 表达文本、音频、图片、视频或 JSON。旧的 Agent 文本输入输出 topic 已删除。
Agent 动作结果使用名为 `robot_task` 的 `small_car.motion.v1` JSON 内容块；它不是速度命令，必须由
树莓派校验后才能转换为 Nav2 Action。

## Topic

| 名称 | 类型 | 约定 |
| --- | --- | --- |
| `/car/camera/image/compressed` | `sensor_msgs/msg/CompressedImage` | 压缩相机图像 |

树莓派音频采集、VAD 缓冲和播放属于 `agent_client` 进程内部实现，通过 `robot_host/core` 的 ALSA
接口直接读写设备，不定义共享音频 Topic。完整 WAV 只在一次 `/car/agent/run` Action 请求或响应的边界传输。

新增接口时优先使用 ROS 标准消息。新增或修改接口时，先更新 YAML，再更新本表中单位、坐标系、QoS、频率和超时语义。
