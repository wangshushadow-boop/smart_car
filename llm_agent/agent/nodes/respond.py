"""Final text response and independent speech synthesis nodes."""

from __future__ import annotations

from llm_agent.adapters.audio.tts import SpeechSynthesizer
from llm_agent.agent.prompt_loader import PromptSet
from llm_agent.agent.state import IntentType
from llm_agent.models.protocol import ModelBackend
from llm_agent.models.response_parser import sanitize_spoken_answer
from llm_agent.models.types import ModelRequest, SpeechRequest
from llm_agent.runtime.contracts import ContentType

from .common import request_inputs


def create_response_node(model: ModelBackend, prompts: PromptSet):
    def respond(state: dict) -> dict:
        progress = state.get("progress_callback")
        if progress:
            progress("generating", 65, "正在生成最终回复")
        decision = state["intent"]
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

        request = state["request"]
        text, audio_urls, image_urls, video_urls = request_inputs(request)
        context = [prompts.response, prompts.safety]
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
    def synthesize_speech(state: dict) -> dict:
        answer = state.get("answer", "")
        if not answer:
            return {}
        request = state["request"]
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
