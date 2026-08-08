"""调用本地 MiniCPM-o Omni 服务完成多模态理解和原生语音生成。"""
from __future__ import annotations
import asyncio
import base64
import json
import os

from openai import OpenAI
import websockets


class MiniCpmClient:
    def __init__(self) -> None:
        self.client = OpenAI(
            base_url=os.getenv("MINICPM_BASE_URL", "http://127.0.0.1:8099/v1"),
            api_key=os.getenv("MINICPM_API_KEY", "EMPTY"),
        )
        self.model = os.getenv("MINICPM_MODEL", "/mnt/d/AI/models/MiniCPM-o-4_5-AWQ")
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
        answer_wav = (
            base64.b64decode(audio_data)
            if audio_data
            else asyncio.run(self._synthesize(answer))
        )
        return {"answer": answer, "answer_wav": answer_wav}

    async def _synthesize(self, text: str) -> bytes:
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
