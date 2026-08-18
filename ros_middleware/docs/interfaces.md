# ROS 接口契约

共享接口定义位于 `src/small_car_interfaces`。发布者和订阅者的业务实现分别保留在 `robot_host`、`llm_agent` 等所属工程。

`src/small_car_interfaces/config/interfaces.yaml` 是 topic、service 和 action 的唯一事实源；
它会随 `small_car_interfaces` 安装。树莓派、WSL Agent 和 Web Debug 都读取该文件。

## Service

| 名称 | 类型 | 约定 |
| --- | --- | --- |
| `/car/agent/run` | `small_car_interfaces/srv/RunAgent` | 提交一轮输入并获得短 DialogueLoop 响应 |
| `/car/audio/enqueue` | `small_car_interfaces/srv/PlayAudio` | Agent Server 主动提交最终 WAV |

## Action

| 名称 | 类型 | 约定 |
| --- | --- | --- |
| `/car/agent/tool_execute` | `small_car_interfaces/action/ExecuteRobotTool` | Agent 请求树莓派执行受限原子工具的唯一接口 |
| `/drive_on_heading` | `nav2_msgs/action/DriveOnHeading` | 树莓派执行受限的相对直线运动 |
| `/spin` | `nav2_msgs/action/Spin` | 树莓派执行受限的原地旋转 |

`/car/agent/run` 的请求使用 `AgentRequest`，响应使用 `AgentResponse`。输入和输出均由
`AgentContent[]` 表达文本、音频、图片、视频或 JSON。Service 只执行短 DialogueLoop；
长 Skill 在后台运行并通过 `/car/agent/tool_execute` 调用树莓派 Gateway。

## Topic

| 名称 | 类型 | 约定 |
| --- | --- | --- |
| `/car/camera/image/compressed` | `sensor_msgs/msg/CompressedImage` | 压缩相机图像 |

树莓派音频采集、VAD 缓冲和播放属于 `agent_client` 进程内部实现，通过 `robot_host/core` 的 ALSA
接口直接读写设备，不定义共享音频 Topic。上传 WAV 通过 `/car/agent/run`，播放 WAV
通过 `/car/audio/enqueue`，两个 Service 都只等待接收或短决策完成。

新增接口时优先使用 ROS 标准消息。新增或修改接口时，先更新 YAML，再更新本表中单位、坐标系、QoS、频率和超时语义。
