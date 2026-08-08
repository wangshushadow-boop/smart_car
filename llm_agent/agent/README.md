# Agent 核心

本目录只放大模型 Agent 的运行代码，不放 ROS 采集、VAD 或底盘控制实现。

| 模块 | 职责 |
| --- | --- |
| `langgraph_runtime.py` | 调用编译后的 LangGraph 图；后续模型路由、记忆和工具节点均从这里组合 |
| `graph.py` | 第一版图：感知事件调用本地 MiniCPM-o 并产生文本回复 |
| `minicpm_client.py` | 本地 OpenAI 兼容 API 的图像、音频与文本调用 |
| `run_agent.py` | 可直接运行的 Agent 入口 |

数据边界：`llm_agent/input` 直接订阅小车发布的音频和压缩图像，并在本地完成 VAD。
Agent 可使用图像和 WAV 进行本轮推理，但长期记忆只应保存转写、摘要和任务状态。
完整运行步骤见[语音对话链路](../docs/agent_ros_voice_loop.md)。
