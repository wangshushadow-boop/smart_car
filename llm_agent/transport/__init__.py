"""Agent 外部传输适配器。

把 Runtime 的纯领域对象与外部协议（ROS 2 Service/Action、未来可能的 HTTP/WebSocket）
相互转换。该包刻意薄：只做消息级映射，业务逻辑由 Runtime 处理。
"""
