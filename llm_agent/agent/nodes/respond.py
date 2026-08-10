"""最终文字回复与独立语音合成节点。

包含两个 LangGraph 节点：
- `create_response_node`：根据意图分发——结构化动作走模板回复，其他走模型。
- `create_speech_node`：调用独立 TTS 后端把 answer 转成 WAV。

设计要点：
- 动作/技能类不调模型，避免模型改写"前进 0.5 米"成含糊描述。
- 模板回复里把 distance/angle 翻译为"前进/后退/左转/右转"，方向与数值一目了然。
- 语音合成失败时只记录 error，文字结果仍保留，避免整轮被判无响应。
"""

from __future__ import annotations

import logging

from llm_agent.adapters.audio.tts import SpeechSynthesizer
from llm_agent.agent.prompt_loader import PromptSet
from llm_agent.agent.state import IntentType
from llm_agent.conversation import format_conversation_history
from llm_agent.models.protocol import ModelBackend
from llm_agent.models.response_parser import sanitize_spoken_answer
from llm_agent.models.types import ModelRequest, SpeechRequest
from llm_agent.runtime.contracts import ContentType

from .common import request_inputs


_MODEL_OUTPUT_LOGGER = logging.getLogger("llm_agent.model_output")


def create_response_node(model: ModelBackend, prompts: PromptSet):
    """构造最终回复节点。"""

    def respond(state: dict) -> dict:
        progress = state.get("progress_callback")
        if progress:
            progress("generating", 65, "正在生成最终回复")
        decision = state["intent"]
        # 结构化动作/技能走模板：避免模型改写关键数值。
        if decision.intent == IntentType.SKILL:
            command = state.get("command")
            if not command:
                return {"answer": "组合任务没有通过安全校验，车辆不会移动。"}
            steps = command.get("steps", [])
            return {
                "answer": f"好的，准备依次执行{len(steps)}个运动步骤。",
                "command": command,
            }
        if decision.intent == IntentType.ACTION:
            command = state.get("command")
            if not command:
                return {
                    "answer": "动作请求没有通过安全校验，车辆不会移动。"
                }
            action = command.get("action")
            if action == "move_relative":
                distance = float(command["distance_m"])
                direction = "前进" if distance > 0 else "后退"
                return {
                    "answer": f"好的，准备{direction}{abs(distance):g}米。",
                    "command": command,
                }
            if action == "rotate_relative":
                angle = float(command["angle_deg"])
                direction = "左转" if angle > 0 else "右转"
                return {
                    "answer": f"好的，准备{direction}{abs(angle):g}度。",
                    "command": command,
                }
            return {"answer": "动作类型不受支持，车辆不会移动。"}
        if decision.intent == IntentType.CANCEL:
            command = state.get("command")
            if command and command.get("action") == "stop_motion":
                return {"answer": "已收到停止请求。", "command": command}
            return {"answer": "停止请求没有通过安全校验。"}
        if decision.intent == IntentType.UNKNOWN:
            return {"answer": "抱歉，我没有听清或理解这个请求，请再说一次。"}

        # CHAT / 状态查询：调模型生成自然语言回复。
        request = state["request"]
        text, audio_urls, image_urls, video_urls = request_inputs(request)
        context = [prompts.response, prompts.safety]
        history = format_conversation_history(state.get("conversation_history", []))
        if history:
            context.append(history)
        if text:
            context.append(f"用户文字：{text}")
        tool_result = state.get("tool_result")
        if tool_result is not None:
            context.append(f"工具结果：{tool_result.model_dump_json()}")
        elif state.get("error"):
            context.append(f"程序错误：{state['error']}")
        try:
            response = model.complete(
                ModelRequest(
                    system_prompt=prompts.system,
                    user_prompt="\n\n".join(context),
                    audio_data_urls=audio_urls,
                    image_data_urls=image_urls,
                    video_data_urls=video_urls,
                    max_tokens=256,
                    temperature=0.2,
                )
            )
            # 在清理思考标签和 Markdown 前记录模型完整原始文本。
            _MODEL_OUTPUT_LOGGER.info(
                "request_id=%s stage=response provider=%s 完整输出：\n%s",
                request.request_id,
                response.provider,
                response.text,
            )
            answer = sanitize_spoken_answer(response.text)
            if not answer:
                answer = "抱歉，我暂时无法给出有效回答。"
            return {"answer": answer, "generation_backend": response.provider}
        except Exception as error:
            return {
                "answer": "模型暂时无法响应，请稍后再试。",
                "error": f"回复生成失败：{error}",
            }

    return respond


def create_speech_node(tts: SpeechSynthesizer):
    """构造语音合成节点：TTS 失败时仅写 error，不影响 answer。"""

    def synthesize_speech(state: dict) -> dict:
        answer = state.get("answer", "")
        if not answer:
            return {}
        request = state["request"]
        # 调用方没声明要音频模态，直接跳过 TTS，省掉无意义的离线推理。
        if ContentType.AUDIO not in request.response_modalities:
            return {}
        progress = state.get("progress_callback")
        if progress:
            progress("synthesizing", 85, "正在生成语音输出")
        try:
            response = tts.synthesize(SpeechRequest(text=answer))
            return {
                "answer_wav": response.audio_wav,
                "speech_backend": response.provider,
            }
        except Exception as error:
            # 独立语音后端失败时仍保留文字结果，避免整轮请求被判定为无响应。
            return {"error": f"语音合成失败：{error}"}

    return synthesize_speech
