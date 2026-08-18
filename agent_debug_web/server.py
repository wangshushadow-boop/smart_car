"""本机 Web 调试服务，只通过 ROS Service 访问 Agent。"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .ros_client import RosAgentClient


class DebugServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False


def create_handler(client: RosAgentClient):
    static_directory = Path(__file__).resolve().parent / "web"

    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "AgentDebugWeb/2.0"

        def do_GET(self) -> None:
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            }
            asset = assets.get(urlparse(self.path).path)
            if asset is None:
                self.send_error(404)
                return
            filename, content_type = asset
            try:
                content = (static_directory / filename).read_bytes()
            except OSError:
                self.send_error(500, "调试页面资源缺失")
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/agent/run":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 96 * 1024 * 1024:
                    raise ValueError("请求体为空或超过 96 MiB")
                payload = json.loads(self.rfile.read(length))
                result = client.submit(payload)
                self._json_response(200, result)
            except (ValueError, json.JSONDecodeError) as error:
                self._json_response(400, {"error": str(error)})
            except Exception as error:
                self._json_response(503, {"error": str(error)})

        def _json_response(self, status: int, payload: dict) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format: str, *_arguments) -> None:
            return

    return RequestHandler


def main() -> None:
    host = os.getenv("AGENT_DEBUG_HOST", "127.0.0.1")
    port = int(os.getenv("AGENT_DEBUG_PORT", "8765"))
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("未鉴权调试服务只能监听本机回环地址")
    client = RosAgentClient()
    server = DebugServer((host, port), create_handler(client))
    print(f"全模态 Agent 调试页面：http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        client.stop()


if __name__ == "__main__":
    main()
