#!/usr/bin/env python3
"""通过 vLLM-Omni WebSocket 生成一段原生 WAV，用于验证语音输出链路。"""

import asyncio
import json
import os
from pathlib import Path

import websockets


async def main() -> None:
    endpoint = os.getenv("MINICPM_OMNI_WS", "ws://127.0.0.1:8099/v1/audio/speech/stream")
    model = os.getenv("MINICPM_OMNI_MODEL", "/mnt/d/AI/models/MiniCPM-o-4_5-AWQ")
    text = os.getenv("MINICPM_OMNI_TEST_TEXT", "你好，我是小车，语音链路已经接通。")
    output = Path(os.getenv("MINICPM_OMNI_TEST_WAV", "/tmp/minicpm_omni_test.wav"))
    audio = bytearray()

    async with websockets.connect(endpoint, proxy=None, max_size=None) as websocket:
        await websocket.send(json.dumps({"type": "session.config", "model": model, "response_format": "wav"}))
        await websocket.send(json.dumps({"type": "input.text", "text": text}, ensure_ascii=False))
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
        raise RuntimeError("服务未返回音频数据")
    output.write_bytes(audio)
    print(f"语音生成成功：{output}（{len(audio)} 字节）")


if __name__ == "__main__":
    asyncio.run(main())
