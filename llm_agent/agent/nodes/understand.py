"""Intent understanding node."""

from __future__ import annotations

from llm_agent.agent.events import BargeIn, TaskCancelled
from llm_agent.agent.prompt_loader import PromptSet
from llm_agent.agent.state import IntentDecision, IntentType
from llm_agent.models.protocol import ModelBackend
from llm_agent.models.response_parser import parse_intent_decision
from llm_agent.models.types import ModelRequest
from llm_agent.tools.types import ToolCall

from .common import event_inputs


def create_understand_node(model: ModelBackend, prompts: PromptSet):
    def understand(state: dict) -> dict:
        event = state["event"]
        if isinstance(event, (BargeIn, TaskCancelled)):
            return {
                "intent": IntentDecision(
                    intent=IntentType.CANCEL, reason="收到取消事件"
                )
            }
        text, speech_wav, image_data_url = event_inputs(event)
        user_prompt = prompts.intent
        if text:
            user_prompt += f"\n\n用户文字：{text}"
        try:
            response = model.complete(
                ModelRequest(
                    system_prompt=prompts.system,
                    user_prompt=user_prompt,
                    speech_wav=speech_wav,
                    image_data_url=image_data_url,
                    max_tokens=160,
                    temperature=0.0,
                )
            )
            decision = parse_intent_decision(response.text)
        except Exception as error:
            decision = IntentDecision(
                intent=IntentType.UNKNOWN, reason=f"意图识别失败：{error}"
            )
        result: dict = {"intent": decision}
        if decision.tool_name:
            result["tool_call"] = ToolCall(
                name=decision.tool_name, arguments=decision.arguments
            )
        return result

    return understand
