"""意图理解节点。

只调用一次模型，输出 `IntentDecision`，必要时附带 `tool_call` 或 `skill_call`。
设计原则：
- 视觉内容（图像 / 视频）不参与意图识别，避免摄像头干扰语音里的"左/右"。
- 生成预算和 temperature 由当前模型能力配置提供。
- 完整原始文本会写入 `llm_agent.model_output` logger，便于排查模型误识别。
"""

from __future__ import annotations

import logging
import math
import re

from llm_agent.agent.prompt_loader import PromptSet
from llm_agent.agent.state import IntentDecision, IntentType
from llm_agent.models.protocol import AsrBackend, ModelBackend
from llm_agent.models.response_parser import parse_json_object
from llm_agent.models.types import ModelRequest, TranscriptionRequest
from llm_agent.skills import SkillCall
from llm_agent.tools.types import ToolCall

from .common import request_inputs


_MODEL_OUTPUT_LOGGER = logging.getLogger("llm_agent.model_output")


def _normalize_rotation_direction(decision: IntentDecision) -> IntentDecision:
    """在 Agent 边界内校验实车旋转语义并归一化方向和角度。"""
    if (
        decision.intent != IntentType.ACTION
        or decision.tool_name != "rotate_relative"
        or "angle_deg" not in decision.arguments
    ):
        return decision

    arguments = dict(decision.arguments)
    direction = arguments.get("direction")
    if direction not in {"left", "right", None}:
        return IntentDecision(
            intent=IntentType.UNKNOWN, reason="旋转任务 direction 字段无效"
        )
    if direction is None:
        reason = decision.reason.lower()
        has_left = "左转" in reason or bool(re.search(r"\bturn\s+left\b", reason))
        has_right = "右转" in reason or bool(re.search(r"\bturn\s+right\b", reason))
        if has_left == has_right:
            return IntentDecision(
                intent=IntentType.UNKNOWN, reason="旋转任务没有唯一明确的左右方向"
            )
        direction = "left" if has_left else "right"

    try:
        angle = float(arguments["angle_deg"])
    except (TypeError, ValueError):
        return IntentDecision(
            intent=IntentType.UNKNOWN, reason="旋转任务角度不是有效数值"
        )
    if not math.isfinite(angle):
        return IntentDecision(
            intent=IntentType.UNKNOWN, reason="旋转任务角度不是有限数值"
        )
    arguments["direction"] = direction
    arguments["angle_deg"] = abs(angle)
    return decision.model_copy(update={"arguments": arguments})


def _parse_intent_decision(text: str) -> IntentDecision:
    """把模型层返回的通用字典转换成 Agent 自己的强类型意图。"""
    try:
        decision = IntentDecision.model_validate(parse_json_object(text))
        return _normalize_rotation_direction(decision)
    except ValueError as error:
        return IntentDecision(intent=IntentType.UNKNOWN, reason=f"意图格式无效：{error}")


def create_understand_node(
    model: ModelBackend,
    prompts: PromptSet,
    skill_catalog: str = "",
    asr: AsrBackend | None = None,
):
    """构造意图理解节点闭包。

    `skill_catalog` 由 `SkillRegistry.catalog_prompt()` 生成，仅暴露 Skill 名 +
    一行描述，避免把所有细节塞进模型上下文。
    """

    def understand(state: dict) -> dict:
        progress = state.get("progress_callback")
        if progress:
            progress("understanding", 15, "正在识别请求意图")
        request = state["request"]
        text, audio_urls, _image_urls, _video_urls = request_inputs(request)
        effective_text = text
        forwarded_audio_urls = audio_urls
        transcript = ""
        asr_provider = ""
        failure_error = ""
        user_prompt = prompts.intent
        if skill_catalog:
            user_prompt += f"\n\n{skill_catalog}"
        try:
            if audio_urls and not model.capabilities.audio_input:
                if asr is None:
                    raise RuntimeError("当前生成模型不支持音频，且 ASR Provider 不可用")
                if progress:
                    progress("transcribing", 12, "正在把语音转换为文字")
                try:
                    transcription = asr.transcribe(
                        TranscriptionRequest(audio_data_urls=audio_urls)
                    )
                except Exception as error:
                    raise RuntimeError(f"ASR 转写失败：{error}") from error
                transcript = transcription.text.strip()
                asr_provider = transcription.provider
                effective_text = "\n".join(filter(None, [text, transcript]))
                forwarded_audio_urls = []
                _MODEL_OUTPUT_LOGGER.info(
                    "request_id=%s stage=asr provider=%s 转写结果：%s",
                    request.request_id,
                    transcription.provider,
                    transcript,
                )
            if effective_text:
                user_prompt += f"\n\n用户文字：{effective_text}"
            response = model.complete(
                ModelRequest(
                    system_prompt=prompts.system,
                    user_prompt=user_prompt,
                    audio_data_urls=forwarded_audio_urls,
                    # 意图分类只需要用户语言；视觉内容留给回复节点，避免摄像头
                    # 画面压过语音中的“左/右”等关键控制词。
                    image_data_urls=[],
                    video_data_urls=[],
                    max_tokens=model.capabilities.intent_max_tokens,
                    temperature=model.capabilities.intent_temperature,
                )
            )
            # 记录解析前的完整原始文本，便于区分模型误识别与解析器问题。
            _MODEL_OUTPUT_LOGGER.info(
                "request_id=%s stage=intent provider=%s 完整输出：\n%s",
                request.request_id,
                response.provider,
                response.text,
            )
            decision = _parse_intent_decision(response.text)
            _MODEL_OUTPUT_LOGGER.info(
                "request_id=%s stage=intent 解析结果：%s",
                request.request_id,
                decision.model_dump_json(),
            )
        except Exception as error:
            # 模型失败：降级为 UNKNOWN，让后续节点走自然语言回复而不是直接动车辆。
            failure_error = f"意图识别失败：{error}"
            decision = IntentDecision(
                intent=IntentType.UNKNOWN, reason=failure_error
            )
        # 文字直接保存；纯语音请求只保存模型生成的意图摘要，不保存 WAV。
        result: dict = {
            "intent": decision,
            "user_summary": effective_text or decision.reason,
        }
        if transcript:
            result["transcript"] = transcript
        if asr_provider:
            result["asr_backend"] = asr_provider
        if failure_error:
            result["error"] = failure_error
        else:
            result["generation_backend"] = response.provider
        if decision.tool_name:
            result["tool_call"] = ToolCall(
                name=decision.tool_name, arguments=decision.arguments
            )
        if decision.skill_name:
            result["skill_call"] = SkillCall(
                name=decision.skill_name, arguments=decision.arguments
            )
        return result

    return understand
