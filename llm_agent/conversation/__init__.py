"""短期多轮对话存储，不依赖 ROS、模型 Provider 或长期记忆系统。

进程重启即清空；可通过 `ConversationStore` Protocol 替换为 SQLite/Redis
实现。当前默认提供 `InMemoryConversationStore` 与关闭会话用的
`NullConversationStore` 两种实现。
"""

from .store import (
    ConversationStore,
    ConversationTurn,
    InMemoryConversationStore,
    NullConversationStore,
    format_conversation_history,
)

__all__ = [
    "ConversationStore",
    "ConversationTurn",
    "InMemoryConversationStore",
    "NullConversationStore",
    "format_conversation_history",
]
