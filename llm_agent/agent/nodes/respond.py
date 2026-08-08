"""Final text response and independent speech synthesis nodes."""

from __future__ import annotations

from llm_agent.adapters.audio.tts import SpeechSynthesizer
from llm_agent.agent.prompt_loader import PromptSet
from llm_agent.agent.state import IntentType
from llm_agent.models.protocol import ModelBackend
from llm_agent.models.response_parser import sanitize_spoken_answer
from llm_agent.models.types import ModelRequest

from .common import event_inputs


def create_response_node(model: ModelBackend, prompts: PromptSet):
    def respond(state: dict) -> dict:
        decision = state["intent"]
        if decision.intent == IntentType.ACTION:
            return {"answer": "当前版本尚未开放车辆动作控制。"}
        if decision.intent == IntentType.CANCEL:
            return {"answer": "已收到停止或取消请求。"}
        if decision.intent == IntentType.UNKNOWN:
            return {"answer": "抱歉，我没有听清或理解这个请求，请再说一次。"}

        event = state["event"]
        text, speech_wav, image_data_url = event_inputs(event)
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
                    speech_wav=speech_wav,
                    image_data_url=image_data_url,
                    max_tokens=256,
                    temperature=0.2,
                )
            )
            answer = sanitize_spoken_answer(response.text)
            if not answer:
                answer = "抱歉，我暂时无法给出有效回答。"
            return {"answer": answer}
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
        try:
            return {"answer_wav": tts.synthesize(answer)}
        except Exception as error:
            # Text remains usable even if the independent speech backend fails.
            return {"error": f"语音合成失败：{error}"}

    return synthesize_speech
