from __future__ import annotations

import json
import unittest
from urllib.request import ProxyHandler, Request, build_opener

from agent_debug_web.server import DebugServer, create_handler


class FakeRosClient:
    def __init__(self) -> None:
        self.payloads = []

    def submit(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {
            "request_id": "request-1",
            "status": "completed",
            "outputs": [{"type": "text", "text": "收到"}],
            "generation_provider": "fake",
            "speech_provider": "",
            "error_message": "",
        }


class DebugServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeRosClient()
        self.server = DebugServer(("127.0.0.1", 0), create_handler(self.client))
        from threading import Thread

        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        host, port = self.server.server_address[:2]
        self.address = f"http://{host}:{port}"
        self.open = build_opener(ProxyHandler({})).open

    def _stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_serves_independent_debug_page(self) -> None:
        with self.open(self.address, timeout=2) as response:
            html = response.read().decode("utf-8")
        self.assertIn("小车 Agent 对话调试", html)
        self.assertIn('id="messageList"', html)
        self.assertIn('id="newConversation"', html)

    def test_forwards_unified_request_to_ros_client(self) -> None:
        payload = {
            "inputs": [{"type": "text", "text": "你好"}],
            "response_modalities": ["text"],
        }
        request = Request(
            self.address + "/api/agent/run",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.open(request, timeout=2) as response:
            result = json.loads(response.read().decode("utf-8"))
        self.assertEqual(result["outputs"][0]["text"], "收到")
        self.assertEqual(self.client.payloads, [payload])


if __name__ == "__main__":
    unittest.main()
