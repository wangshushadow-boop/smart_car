"""Agent 应用层入口包。

对外暴露两个核心能力：
- `app.config`：加载并校验 `agent.yaml` 与环境变量覆盖。
- `app.run_agent`：ROS 2 Action Server 主入口（`main()`）。

该包刻意保持轻量，不依赖 LangGraph、模型 Provider 或具体 Tool；
具体编排由 `runtime/` 与 `agent/` 负责。
"""
