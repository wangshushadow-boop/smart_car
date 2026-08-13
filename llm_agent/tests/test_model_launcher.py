from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from llm_agent.scripts.start_models import command_for, main, process_environment


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

    def test_command_is_read_from_yaml_without_model_specific_branch(self) -> None:
        command = command_for(
            "future_model",
            {
                "command": [
                    "/env/future/bin/python",
                    "-m",
                    "vendor.future.server",
                    "--port",
                    8200,
                ]
            },
        )
        self.assertEqual(
            command,
            [
                "/env/future/bin/python",
                "-m",
                "vendor.future.server",
                "--port",
                "8200",
            ],
        )

    def test_invalid_command_reports_model_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "piper"):
            command_for("piper", {"command": "piper"})

    def test_environment_adds_model_specific_values(self) -> None:
        with patch.dict("os.environ", {"EXISTING": "kept"}, clear=True):
            environment = process_environment(
                "future_model", {"environment": {"CUDA_VISIBLE_DEVICES": 0}}
            )
        self.assertEqual(environment["EXISTING"], "kept")
        self.assertEqual(environment["CUDA_VISIBLE_DEVICES"], "0")


if __name__ == "__main__":
    unittest.main()
