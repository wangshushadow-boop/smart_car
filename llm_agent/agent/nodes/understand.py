"""Intent understanding node."""

from __future__ import annotations

import logging

from llm_agent.agent.prompt_loader import PromptSet
from llm_agent.agent.state import IntentDecision, IntentType
from llm_agent.models.protocol import ModelBackend
from llm_agent.models.response_parser import parse_intent_decision
from llm_agent.models.types import ModelRequest
from llm_agent.tools.types import ToolCall

from .common import request_inputs


_MODEL_OUTPUT_LOGGER = logging.getLogger("llm_agent.model_output")


def create_understand_node(model: ModelBackend, prompts: PromptSet):
    def understand(state: dict) -> dict:
        progress = state.get("progress_callback")
        if progress:
            progress("understanding", 15, "正在识别请求意图")
        request = state["request"]
        text, audio_urls, _image_urls, _video_urls = request_inputs(request)
        user_prompt = prompts.intent
        if text:
            user_prompt += f"\n\n用户文字：{text}"
        try:
            response = model.complete(
                ModelRequest(
                    system_prompt=prompts.system,
                    user_prompt=user_prompt,
                    audio_data_urls=audio_urls,
                    # 意图分类只需要用户语言；视觉内容留给回复节点，避免摄像头
                    # 画面压过语音中的“左/右”等关键控制词。
                    image_data_urls=[],
                    video_data_urls=[],
                    max_tokens=160,
                    temperature=0.0,
                )
            )
            # 记录解析前的完整原始文本，便于区分模型误识别与解析器问题。
            _MODEL_OUTPUT_LOGGER.info(
                "request_id=%s stage=intent provider=%s 完整输出：\n%s",
                request.request_id,
                response.provider,
                response.text,
            )
            decision = parse_intent_decision(response.text)
            _MODEL_OUTPUT_LOGGER.info(
                "request_id=%s stage=intent 解析结果：%s",
                request.request_id,
                decision.model_dump_json(),
            )
        except Exception as error:
            decision = IntentDecision(
                intent=IntentType.UNKNOWN, reason=f"意图识别失败：{error}"
            )
        # 文字直接保存；纯语音请求只保存模型生成的意图摘要，不保存 WAV。
        result: dict = {
            "intent": decision,
            "user_summary": text or decision.reason,
        }
        if decision.tool_name:
            result["tool_call"] = ToolCall(
                name=decision.tool_name, arguments=decision.arguments
            )
        return result

    return understand
