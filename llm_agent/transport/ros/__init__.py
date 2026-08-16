"""统一 ROS 2 Action 传输层。

`run_agent_server.py` 把 `AgentGateway` 暴露为 `/car/agent/run`，并集中处理
消息转换、接口名字契约和可选 tracing；`robot_tool_client.py` 只负责调用
树莓派 Robot Tool Gateway，`audio_output_client.py` 只负责提交最终语音。

新增 ROS 集成时务必遵守该层的边界，避免把 ROS 类型泄漏到 `runtime/` 或
Agent 核心内。
"""
