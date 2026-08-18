"""DialogueLoop 与 SkillRunner 共用的单步 ReAct 决策器。"""

from __future__ import annotations

import logging

from llm_agent.models.protocol import GenerationBackend, parse_json_object

from .contracts import AgentDecision

_MODEL_OUTPUT_LOGGER = logging.getLogger("llm_agent.model_output")


class Reactor:
    """只负责一次 Reason 决策，不包含对话或机器人任务业务。"""

    def __init__(self, model: GenerationBackend) -> None:
        self._model = model

    @property
    def provider_name(self) -> str:
        return self._model.provider_name

    def decide(
        self,
        *,
        request_id: str,
        stage: str,
        turn: int,
        prompt,
    ) -> tuple[AgentDecision, str]:
        """调用模型、记录原始输出并解析成统一决策。"""
        response = self._model.complete(prompt)
        _MODEL_OUTPUT_LOGGER.info(
            "request_id=%s stage=%s turn=%s provider=%s 完整输出：\n%s",
            request_id,
            stage,
            turn,
            response.provider,
            response.text,
        )
        decision = AgentDecision.model_validate(parse_json_object(response.text))
        return decision, response.provider
