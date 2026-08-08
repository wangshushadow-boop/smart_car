# Agent 核心

本目录只负责事件、状态、LangGraph 编排和运行生命周期，不实现 ROS 采集、模型传输或 TTS。

| 路径 | 职责 |
| --- | --- |
| `events.py` | Agent 接收的强类型事件和旧字典事件兼容转换 |
| `state.py` | LangGraph 单轮状态、意图类型和结构化意图结果 |
| `runtime.py` | 串行执行、停止信号和图调用边界 |
| `graph.py` | 意图识别、工具白名单检查、执行、回复和 TTS 的流程编排 |
| `nodes/` | 各个职责单一的 LangGraph 节点 |
| `prompt_loader.py` | 加载仓库内版本化提示词 |

其他边界：

- `llm_agent/models` 封装 MiniCPM-o 和模型输出解析；
- `llm_agent/tools` 定义强类型白名单工具；
- `llm_agent/adapters/audio` 封装独立 TTS；
- `llm_agent/input` 继续负责 ROS 音视频聚合、VAD 和回声抑制，后续再渐进拆分。

当前仅开放只读的 `get_robot_status` 工具。在 ROS 状态网关实现前，它会明确返回不可用；车辆动作工具尚未开放。
详细设计见[Agent 架构](../docs/architecture.md)、[状态与事件](../docs/agent_state.md)和
[工具契约](../docs/tool_contract.md)；完整运行步骤见[语音对话链路](../docs/agent_ros_voice_loop.md)。
