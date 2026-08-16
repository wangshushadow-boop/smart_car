"""Agent 应用层入口包。

`app.run_agent` 是 ROS 2 Action Server 的唯一进程入口；配置模型与加载函数
位于顶层 `config/` 包。

该包刻意保持轻量，不依赖模型 Provider 或具体 Tool；
具体编排由 `runtime/` 负责。
"""
