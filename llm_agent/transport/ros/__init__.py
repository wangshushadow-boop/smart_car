"""统一 ROS 2 Action 传输层。

把 `AgentRuntime` 暴露为 `/car/agent/run` Action Server：
- `AgentActionServer`：Node + ActionServer，处理 Goal / Cancel / Feedback / Result。
- `converters`：在 ROS 消息与 Runtime 领域对象之间双向映射。
- `interface_contract`：从 `small_car_interfaces` 包加载 Action 名字契约。

新增 ROS 集成时务必遵守该层的边界，避免把 ROS 类型泄漏到 `runtime/` 或
`agent/` 内。
"""
