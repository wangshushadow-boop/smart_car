"""LangGraph 节点在一轮 Agent 请求里共享的状态定义。

`AgentState` 用 `TypedDict(total=False)`，所有字段都是可选的——节点只写入
自己关心的键，未填的键表示该步骤未参与本轮路径。

关键字段语义：
- `request`/`request_id`/`cancel_token`/`progress_callback`：由 Runtime 注入。
- `intent`/`tool_call`/`skill_call`：模型在 `understand_intent` 节点写入。
- `skill_plan`/`skill_result`/`tool_result`：校验与执行节点的中间产物。
- `command`：声明式 ROS 任务（仅 Tool 成功且 schema=motion 时写入）。
- `answer`/`answer_wav`：最终回复文本与语音。
- `error`：任一节点失败都会写入，下游 `route_safety` 据此切换分支。
"""

from __future__ import annotations

from enum import Enum
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field

from llm_agent.conversation import ConversationTurn
from llm_agent.runtime.contracts import RuntimeRequest
from llm_agent.skills import SkillCall, SkillPlan, SkillPlanResult


class IntentType(str, Enum):
    """意图分类。

    - `CHAT`：闲聊，模型直接生成回复。
    - `QUERY`：查询车辆状态，对应 `get_robot_status` Tool。
    - `ACTION`：单步运动，对应 `move_relative` / `rotate_relative` Tool。
    - `CANCEL`：停止请求，对应 `stop_motion` Tool。
    - `SKILL`：组合任务，对应 `motion_sequence` Skill。
    - `UNKNOWN`：模型未给出合法 JSON 或语义含糊，统一降级为自然语言回复。
    """

    CHAT = "chat"
    QUERY = "query"
    ACTION = "action"
    CANCEL = "cancel"
    SKILL = "skill"
    UNKNOWN = "unknown"


class IntentDecision(BaseModel):
    """模型在 `understand_intent` 节点输出的结构化意图。

    `tool_name` 与 `skill_name` 互斥：选择 Tool 时 `skill_name` 必须为 None，
    反之亦然。`reason` 用于解释识别失败或方向模糊的原因，会进入对话历史。
    """

    model_config = ConfigDict(extra="forbid")

    intent: IntentType
    tool_name: str | None = None
    skill_name: str | None = None
    arguments: dict = Field(default_factory=dict)
    reason: str = ""


class AgentState(TypedDict, total=False):
    """LangGraph 状态字典。

    字段命名说明：
    - 所有 *_backend 字段记录实际使用的 Provider 名称，便于日志与诊断。
    - `command` 字典结构见 `MOTION_TASK_SCHEMA` / `MOTION_SEQUENCE_SCHEMA`。
    """

    request_id: str
    request: RuntimeRequest
    cancel_token: object
    progress_callback: object
    conversation_history: list[ConversationTurn]
    user_summary: str
    intent: IntentDecision
    tool_call: object
    skill_call: SkillCall
    skill_plan: SkillPlan
    skill_result: SkillPlanResult
    tool_result: object
    command: dict
    answer: str
    answer_wav: bytes
    generation_backend: str
    speech_backend: str
    error: str
