"""LangGraph 节点工厂聚合。

每个节点都通过工厂函数（`create_xxx_node`）返回内部闭包，让 LangGraph 拿到
一个 `(state) -> dict` 的可调用对象。这样可以：
- 注入依赖（模型实例、Tool 白名单、Skill 白名单、Prompt 集）。
- 在单元测试里直接传假依赖覆盖单条路径。
"""

from .execute_tool import create_execute_tool_node
from .execute_skill import create_execute_skill_node, create_skill_safety_node
from .respond import create_response_node, create_speech_node
from .safety_check import create_safety_check_node
from .understand import create_understand_node

__all__ = [
    "create_execute_tool_node",
    "create_execute_skill_node",
    "create_response_node",
    "create_safety_check_node",
    "create_skill_safety_node",
    "create_speech_node",
    "create_understand_node",
]
