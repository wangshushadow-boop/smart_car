"""Piper 独立 HTTP 服务。

服务负责持有模型路径并调用 Piper CLI；Agent 只通过 HTTP 客户端访问它。
提供 ``GET /health`` 和 ``POST /synthesize``，使用标准库实现以避免新增 Web
框架依赖。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llm_agent.models.protocol import inspect_pcm16_wav


class PiperEngine:
    """封装一次 Piper CLI 合成所需的部署参数。"""

    def __init__(self, model: str, config: str, timeout: float) -> None:
        """保存 ONNX 模型、配置文件和单次合成超时。"""
        self._model = model
        self._config = config
        self._timeout = timeout

    def synthesize(self, text: str) -> dict:
        """调用当前环境中的 Piper，读取、校验并 Base64 编码 WAV。"""
        output_path: str | None = None
        try:
            # Piper CLI 需要输出文件；使用唯一临时文件避免并发请求互相覆盖。
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output:
                output_path = output.name
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "piper",
                    "--model",
                    self._model,
                    "--config",
                    self._config,
                    "--output-file",
                    output_path,
                ],
                input=text.encode("utf-8"),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self._timeout,
            )
            with open(output_path, "rb") as output:
                audio = output.read()
        finally:
            # 无论 Piper 成功还是抛错都清理临时文件。
            if output_path:
                try:
                    os.unlink(output_path)
                except FileNotFoundError:
                    pass
        sample_rate, channels = inspect_pcm16_wav(audio)
        return {
            "audio_wav_base64": base64.b64encode(audio).decode("ascii"),
            "provider": "piper",
            "sample_rate": sample_rate,
            "channels": channels,
        }


def create_handler(engine: PiperEngine):
    """创建绑定 Engine 的 HTTP Handler 类型。"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """提供不触发语音合成的轻量健康检查。"""
            if self.path != "/health":
                self.send_error(404)
                return
            self._json(200, {"status": "ready", "model": "piper"})

        def do_POST(self) -> None:
            """处理短文本语音合成请求，并限制请求体大小。"""
            if self.path != "/synthesize":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 64 * 1024:
                    raise ValueError("request body is empty or too large")
                text = str(json.loads(self.rfile.read(length)).get("text", "")).strip()
                if not text:
                    raise ValueError("text must not be empty")
                self._json(200, engine.synthesize(text))
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
            """关闭逐请求访问日志。"""
            return

    return Handler


def main() -> None:
    """解析部署参数并以前台方式启动 Piper 服务。"""
    parser = argparse.ArgumentParser(
        description="启动独立 Piper HTTP 语音合成服务。",
        epilog=(
            "接口：GET /health，POST /synthesize。\n"
            "通常无需直接运行，请使用 scripts/start_models.sh。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出")
    parser.add_argument("--model", required=True, help="Piper ONNX 模型路径")
    parser.add_argument("--config", required=True, help="Piper ONNX JSON 配置路径")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8101, help="监听端口（默认：8101）")
    parser.add_argument(
        "--timeout", type=float, default=30, help="单次 Piper CLI 超时秒数（默认：30）"
    )
    args = parser.parse_args()
    engine = PiperEngine(args.model, args.config, args.timeout)
    server = ThreadingHTTPServer((args.host, args.port), create_handler(engine))
    print(f"Piper ready: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
