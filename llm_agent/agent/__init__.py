"""小车 Agent 运行时：事件处理、模型路由与工具调度。

`agent/` 包承载 LangGraph 状态机本身，节点实现位于 `agent/nodes/`。
该包刻意不导入 ROS 或模型 Provider 的具体实现——所有依赖通过
`runtime/factory.py` 注入，便于单测替换。
"""
