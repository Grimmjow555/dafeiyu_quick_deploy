from __future__ import annotations

import os
import sys
import time
import unittest

from tests.helpers import ROOT  # noqa: F401 - 确保项目根在 sys.path

from dafeiyu_gui.backend.runner import ProcessSession


class ProcessSessionTests(unittest.TestCase):
    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def test_streams_utf8_and_accepts_input(self) -> None:
        lines: list[str] = []
        outcomes = []
        code = (
            "import sys\n"
            "print('第一行 中文')\n"
            "sys.stdout.flush()\n"
            "answer = sys.stdin.readline().strip()\n"
            "print('收到:' + answer)\n"
            "sys.exit(3 if answer == 'fail' else 0)\n"
        )
        session = ProcessSession(
            [sys.executable, "-c", code],
            ROOT,
            lines.append,
            outcomes.append,
            env=self._env(),
        )
        session.start()
        deadline = time.time() + 10
        while not lines and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(any("第一行 中文" in line for line in lines))
        self.assertTrue(session.send_input("ok\n"))
        self.assertTrue(session.wait(10))
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].exit_code, 0)
        self.assertFalse(outcomes[0].canceled)
        self.assertIn("收到:ok", lines)

    def test_cancel(self) -> None:
        lines: list[str] = []
        outcomes = []
        code = "import sys, time\nprint('started', flush=True)\ntime.sleep(30)\n"
        session = ProcessSession(
            [sys.executable, "-c", code],
            ROOT,
            lines.append,
            outcomes.append,
            env=self._env(),
        )
        session.start()
        deadline = time.time() + 10
        while not lines and time.time() < deadline:
            time.sleep(0.02)
        session.cancel()
        self.assertTrue(session.wait(15))
        self.assertEqual(len(outcomes), 1)
        self.assertTrue(outcomes[0].canceled)

    def test_launch_error(self) -> None:
        outcomes = []
        session = ProcessSession(
            ["this-executable-does-not-exist-dafeiyu.exe"],
            ROOT,
            lambda _line: None,
            outcomes.append,
        )
        session.start()
        self.assertTrue(session.wait(10))
        self.assertEqual(outcomes[0].exit_code, -1)
        self.assertTrue(outcomes[0].launch_error)

    def test_callback_error_does_not_hang(self) -> None:
        outcomes = []

        def broken(_line: str) -> None:
            raise RuntimeError("view error")

        code = "print('x')\n"
        session = ProcessSession(
            [sys.executable, "-c", code],
            ROOT,
            broken,
            outcomes.append,
            env=self._env(),
        )
        session.start()
        self.assertTrue(session.wait(10))
        self.assertIsNotNone(session.callback_error)
        self.assertEqual(outcomes[0].exit_code, 0)


if __name__ == "__main__":
    unittest.main()
