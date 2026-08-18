"""与 ROS、HTTP 和设备实现无关的 Agent 执行核心。

`runtime/` 是 Agent 与外部世界之间的稳定边界：
- 上游（ROS Action、调试 Web、单元测试）只接触 `RuntimeRequest/Response`。
- 下游（DialogueLoop、SkillRunner、模型 Provider、Skill/Tool）由 Runtime 统一调度。
任何模块新增依赖前请确认不引入 ROS 类型或设备驱动；外部通信放入
`transport/`，模型调用放入 `models/`。
"""

from .contracts import (
    AgentDecision,
    ContentPart,
    ContentType,
    RuntimeProgress,
    RuntimeRequest,
    RuntimeResponse,
    TaskSnapshot,
)
from .runtime import AgentRuntime
from llm_agent.sessions import ConversationTurn, InMemoryConversationStore

__all__ = [
    "AgentRuntime",
    "AgentDecision",
    "ContentPart",
    "ContentType",
    "ConversationTurn",
    "InMemoryConversationStore",
    "RuntimeProgress",
    "RuntimeRequest",
    "RuntimeResponse",
    "TaskSnapshot",
]
