from __future__ import annotations

import unittest
from unittest.mock import patch

from llm_agent.transport.ros.tracing import ros_trace_scope


class _TraceLibrary:
    def __init__(self) -> None:
        self.calls = []

    def ros_trace_rclcpp_callback_register(self, pointer, name) -> None:
        self.calls.append(("register", pointer.value, name))

    def ros_trace_callback_start(self, pointer, is_intra_process) -> None:
        self.calls.append(("start", pointer.value, is_intra_process))

    def ros_trace_callback_end(self, pointer) -> None:
        self.calls.append(("end", pointer.value))


class RosTracingTest(unittest.TestCase):
    def test_missing_trace_library_is_a_noop(self) -> None:
        with patch("llm_agent.transport.ros.tracing._trace_library", return_value=None):
            with ros_trace_scope(lambda: None, "callback"):
                value = 1
        self.assertEqual(value, 1)

    def test_emits_balanced_events_with_stable_bound_method_identity(self) -> None:
        library = _TraceLibrary()

        class Target:
            def callback(self) -> None:
                return None

        target = Target()
        with patch("llm_agent.transport.ros.tracing._trace_library", return_value=library):
            with ros_trace_scope(target.callback, "Target.callback"):
                pass
            with ros_trace_scope(target.callback, "Target.callback"):
                pass

        pointers = [call[1] for call in library.calls]
        self.assertEqual(len(set(pointers)), 1)
        self.assertEqual(
            [call[0] for call in library.calls],
            ["register", "start", "end", "register", "start", "end"],
        )

    def test_emits_end_when_callback_raises(self) -> None:
        library = _TraceLibrary()
        callback = lambda: None

        with patch("llm_agent.transport.ros.tracing._trace_library", return_value=library):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with ros_trace_scope(callback, "callback"):
                    raise RuntimeError("boom")

        self.assertEqual(
            [call[0] for call in library.calls],
            ["register", "start", "end"],
        )


if __name__ == "__main__":
    unittest.main()
