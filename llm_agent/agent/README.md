# Agent 核心

本目录只负责状态和 LangGraph 业务编排，不实现 Runtime 生命周期、ROS、设备采集或 Web Debug。

| 路径 | 职责 |
| --- | --- |
| `state.py` | LangGraph 单轮状态、意图类型和结构化意图结果 |
| `graph.py` | 意图识别、工具白名单检查、执行、回复和 TTS 的流程编排 |
| `nodes/` | 各个职责单一的 LangGraph 节点 |
| `prompt_loader.py` | 加载仓库内版本化提示词 |

其他边界：

- `llm_agent/runtime` 定义统一全模态请求、响应、进度、取消和执行生命周期；
- `llm_agent/transport/ros` 提供唯一的 `RunAgent` Action Server；
- `llm_agent/models` 封装本地/云端推理、语音、能力声明和 provider 选择；
- `llm_agent/tools` 定义强类型白名单工具；
- `llm_agent/adapters/audio` 封装独立 TTS；
- 树莓派 `robot_host/ros/agent_client` 负责 VAD、画面聚合和硬件播放；
- 仓库顶层 `agent_debug_web` 是完全独立的 Action Client。

当前开放只读的 `get_robot_status`，以及生成声明式任务的 `move_relative`、`rotate_relative`、
`stop_motion`。动作工具不在 Agent Server 访问硬件；树莓派收到任务后还会执行第二次安全校验。
详细设计见[Agent 架构](../docs/architecture.md)、[模型 Provider](../docs/model_providers.md)、
[状态与事件](../docs/agent_state.md)和[工具契约](../docs/tool_contract.md)；完整运行步骤见
[语音对话链路](../docs/agent_ros_voice_loop.md)。
