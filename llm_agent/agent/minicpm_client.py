"""调用本地 MiniCPM-o Omni 服务完成多模态理解和原生语音生成。"""
from __future__ import annotations
import base64
import os
import re
import subprocess
import sys
import tempfile

from openai import OpenAI


def sanitize_spoken_answer(text: str) -> str:
    """Keep only the user-facing final response before speech synthesis."""
    # MiniCPM-o may expose its multimodal trace as an unclosed ``<think`` block.
    # In that form, only a plain ``[AI助手]实际回复`` segment is safe to speak.
    assistant_segments = re.findall(
        r"\[AI助手\]\s*(?!\[)([^\[\n]+)", text, flags=re.IGNORECASE
    )
    if assistant_segments:
        text = assistant_segments[-1]
    elif re.match(r"\s*<think\b", text, flags=re.IGNORECASE) and not re.search(
        r"</think>", text, flags=re.IGNORECASE
    ):
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"<(?:tool|function|analysis|commentary)[^>]*>.*?</(?:tool|function|analysis|commentary)>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(
        r"^\s*(?:assistant|final(?:_answer)?|回答|答复)\s*[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[`*_#>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class MiniCpmClient:
    def __init__(self) -> None:
        self.client = OpenAI(
            base_url=os.getenv("MINICPM_BASE_URL", "http://127.0.0.1:8099/v1"),
            api_key=os.getenv("MINICPM_API_KEY", "EMPTY"),
        )
        self.model = os.getenv("MINICPM_MODEL", "/mnt/d/AI/models/MiniCPM-o-4_5-AWQ")
        self.tts_python = os.getenv("CAR_TTS_PYTHON", sys.executable)
        self.tts_model = os.getenv(
            "CAR_TTS_MODEL",
            "/home/llm_agent/.local/share/piper/zh_CN-huayan-medium/zh_CN-huayan-medium.onnx",
        )
        self.tts_config = os.getenv("CAR_TTS_CONFIG", self.tts_model + ".json")
        self.speech_endpoint = os.getenv(
            "MINICPM_OMNI_WS", "ws://127.0.0.1:8099/v1/audio/speech/stream"
        )

    def respond(self, event: dict) -> dict:
        content = [{"type": "text", "text": "你是语音助手。结合用户语音和当前画面，用简洁中文回答。"}]
        image = event["perception"].get("image_data_url")
        if image:
            content.append({"type": "image_url", "image_url": {"url": image}})
        if event.get("speech_wav"):
            audio_url = "data:audio/wav;base64," + base64.b64encode(
                event["speech_wav"]
            ).decode("ascii")
            content.append({"type": "audio_url", "audio_url": {"url": audio_url}})
        result = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=256,
            temperature=0.2,
        )
        answer = next(
            (choice.message.content for choice in result.choices if choice.message.content),
            "（模型未返回文本）",
        )
        answer = sanitize_spoken_answer(answer)
        if not answer:
            answer = "抱歉，我暂时无法给出有效回答。"
        # vLLM-Omni 会把文本与原生 WAV 放在同一响应的不同 choice 中。
        # 部分版本只返回文本，此时再使用语音 WebSocket 兼容回退。
        audio_data = next(
            (
                getattr(choice.message.audio, "data", None)
                for choice in result.choices
                if getattr(choice.message, "audio", None)
            ),
            None,
        )
        # Do not play native completion audio: it has no verified final-answer association.
        answer_wav = self._synthesize(answer)
        return {"answer": answer, "answer_wav": answer_wav}

    async def _synthesize_omni_unsupported(self, text: str) -> bytes:
        audio = bytearray()
        async with websockets.connect(
            self.speech_endpoint, proxy=None, max_size=None
        ) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "type": "session.config",
                        "model": self.model,
                        "response_format": "wav",
                    }
                )
            )
            await websocket.send(
                json.dumps({"type": "input.text", "text": text}, ensure_ascii=False)
            )
            await websocket.send(json.dumps({"type": "input.done"}))
            while True:
                message = await websocket.recv()
                if isinstance(message, bytes):
                    audio.extend(message)
                    continue
                event = json.loads(message)
                if event.get("type") == "error":
                    raise RuntimeError(event.get("message", "未知语音生成错误"))
                if event.get("type") == "session.done":
                    break
            await websocket.send(json.dumps({"type": "session.close"}))
        if not audio:
            raise RuntimeError("MiniCPM-o 未返回语音")
        return bytes(audio)

    def _synthesize(self, text: str) -> bytes:
        """Generate WAV with the independent Piper Chinese TTS backend."""
        output_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
                output_path = output_file.name
            result = subprocess.run(
                [
                    self.tts_python,
                    "-m",
                    "piper",
                    "--model",
                    self.tts_model,
                    "--config",
                    self.tts_config,
                    "--output-file",
                    output_path,
                ],
                input=text.encode("utf-8"),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            with open(output_path, "rb") as output_file:
                audio = output_file.read()
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(f"external TTS failed: {error}") from error
        finally:
            if output_path:
                try:
                    os.unlink(output_path)
                except FileNotFoundError:
                    pass
        if not audio:
            raise RuntimeError("external TTS returned an empty WAV")
        return audio
