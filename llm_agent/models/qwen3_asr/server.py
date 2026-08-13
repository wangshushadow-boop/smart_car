"""Qwen3-ASR 独立 HTTP 服务。

服务启动时加载一次模型，随后通过 ``POST /transcribe`` 串行执行 GPU 推理；
``GET /health`` 只有在权重加载完成后才可访问。服务不导入 Agent、Runtime、
ROS、Tool 或 Skill。
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock


class Qwen3AsrEngine:
    """服务进程独占的模型实例。"""

    def __init__(self, model_path: str, device: str) -> None:
        """加载指定目录中的 Qwen3-ASR 权重到目标设备。"""
        # 重依赖只在模型服务进程中导入，Agent 环境无需安装它们。
        import torch
        from qwen_asr import Qwen3ASRModel

        self._model = Qwen3ASRModel.from_pretrained(
            model_path,
            dtype=torch.bfloat16,
            device_map=device,
            max_inference_batch_size=1,
            max_new_tokens=256,
        )
        self._lock = Lock()

    def transcribe(self, audio: list[str], language: str | None) -> dict:
        """串行转写一组 data URL，并返回可直接编码为 JSON 的结果。"""
        # qwen-asr 的模型对象不保证并发安全，同时串行可防止显存突增。
        with self._lock:
            results = self._model.transcribe(
                audio=audio,
                language=[language] * len(audio) if language else None,
            )
        texts = [str(getattr(result, "text", "")).strip() for result in results]
        text = "\n".join(value for value in texts if value)
        if not text:
            raise RuntimeError("Qwen3 ASR returned empty transcription")
        languages = {
            str(getattr(result, "language", "")).strip()
            for result in results
            if getattr(result, "language", "")
        }
        return {
            "text": text,
            "provider": "qwen3_asr",
            "language": next(iter(languages)) if len(languages) == 1 else "",
        }


def create_handler(engine: Qwen3AsrEngine):
    """创建绑定单个 Engine 的 HTTP Handler 类型，便于测试时注入假实现。"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """提供统一健康检查；实例化 Handler 前模型已经完成加载。"""
            if self.path != "/health":
                self.send_error(404)
                return
            self._json(200, {"status": "ready", "model": "qwen3_asr"})

        def do_POST(self) -> None:
            """校验并处理转写请求，限制请求体以防止内存被异常输入耗尽。"""
            if self.path != "/transcribe":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 96 * 1024 * 1024:
                    raise ValueError("request body is empty or too large")
                payload = json.loads(self.rfile.read(length))
                audio = payload.get("audio_data_urls")
                if not isinstance(audio, list) or not audio:
                    raise ValueError("audio_data_urls must be a non-empty list")
                self._json(200, engine.transcribe(audio, payload.get("language")))
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {"error": str(error)})
            except Exception as error:
                self._json(500, {"error": f"{type(error).__name__}: {error}"})

        def _json(self, status: int, payload: dict) -> None:
            """发送 UTF-8 JSON 响应。"""
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format: str, *_args) -> None:
            """关闭标准库逐请求访问日志，模型启动日志保持简洁。"""
            return

    return Handler


def main() -> None:
    """解析部署参数、加载模型并以前台方式提供 HTTP 服务。"""
    parser = argparse.ArgumentParser(
        description="启动独立 Qwen3-ASR HTTP 服务。",
        epilog=(
            "接口：GET /health，POST /transcribe。\n"
            "通常无需直接运行，请使用 scripts/start_models.sh。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出")
    parser.add_argument("--model", required=True, help="Qwen3-ASR 模型目录")
    parser.add_argument("--device", default="cuda:0", help="推理设备（默认：cuda:0）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8100, help="监听端口（默认：8100）")
    args = parser.parse_args()
    engine = Qwen3AsrEngine(args.model, args.device)
    server = ThreadingHTTPServer((args.host, args.port), create_handler(engine))
    print(f"Qwen3-ASR ready: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
