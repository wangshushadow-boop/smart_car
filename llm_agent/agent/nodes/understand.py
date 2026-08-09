"""Intent understanding node."""

from __future__ import annotations

from llm_agent.agent.prompt_loader import PromptSet
from llm_agent.agent.state import IntentDecision, IntentType
from llm_agent.models.protocol import ModelBackend
from llm_agent.models.response_parser import parse_intent_decision
from llm_agent.models.types import ModelRequest
from llm_agent.tools.types import ToolCall

from .common import request_inputs


def create_understand_node(model: ModelBackend, prompts: PromptSet):
    def understand(state: dict) -> dict:
        progress = state.get("progress_callback")
        if progress:
            progress("understanding", 15, "正在识别请求意图")
        request = state["request"]
        text, audio_urls, image_urls, video_urls = request_inputs(request)
        user_prompt = prompts.intent
        if text:
            user_prompt += f"\n\n用户文字：{text}"
        try:
            response = model.complete(
                ModelRequest(
                    system_prompt=prompts.system,
                    user_prompt=user_prompt,
                    audio_data_urls=audio_urls,
                    image_data_urls=image_urls,
                    video_data_urls=video_urls,
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
