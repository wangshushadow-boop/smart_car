from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from llm_agent.scripts.start_models import command_for, main


class ModelLauncherTest(unittest.TestCase):
    def test_no_model_prints_help_without_starting_models(self) -> None:
        output = StringIO()
        with patch("sys.argv", ["start_models.py"]), redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertIn("按名称启动", output.getvalue())

    def test_list_prints_local_models(self) -> None:
        with TemporaryDirectory() as temporary:
            config = Path(temporary) / "models.yaml"
            config.write_text(
                """
models:
  minicpm:
    roles: [generation_model]
    deployment: {local: true}
  minimax:
    roles: [generation_model]
    deployment: {local: false}
  piper:
    roles: [speech]
    deployment: {local: true}
""",
                encoding="utf-8",
            )
            output = StringIO()
            with patch(
                "sys.argv", ["start_models.py", "--config", str(config), "--list"]
            ), redirect_stdout(output):
                self.assertEqual(main(), 0)
        self.assertIn("minicpm: generation_model", output.getvalue())
        self.assertIn("piper: speech", output.getvalue())
        self.assertNotIn("minimax", output.getvalue())

    def test_qwen_command_uses_isolated_service_environment(self) -> None:
        command = command_for(
            "qwen3_asr",
            {
                "command": "qwen3_asr",
                "python": "/env/qwen/bin/python",
                "model": "/models/qwen",
                "device": "cuda:0",
                "port": 8100,
            },
        )
        self.assertEqual(command[0], "/env/qwen/bin/python")
        self.assertIn("llm_agent.models.qwen3_asr.server", command)
        self.assertIn("/models/qwen", command)

    def test_piper_command_uses_service_entrypoint(self) -> None:
        command = command_for(
            "piper",
            {
                "command": "piper",
                "python": "/env/agent/bin/python",
                "model": "/models/piper.onnx",
                "config": "/models/piper.onnx.json",
                "port": 8101,
            },
        )
        self.assertEqual(command[0], "/env/agent/bin/python")
        self.assertIn("llm_agent.models.piper.server", command)
        self.assertIn("/models/piper.onnx", command)


if __name__ == "__main__":
    unittest.main()
