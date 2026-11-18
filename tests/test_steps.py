from __future__ import annotations

import unittest

from tests.helpers import ROOT  # noqa: F401 - 确保项目根在 sys.path

from dafeiyu_gui.backend.runner import LineBuffer, TextDecoder, strip_ansi
from dafeiyu_gui.backend.steps import STEP_LABELS, StepTracker


class StepTrackerTests(unittest.TestCase):
    def test_progression_and_no_regression(self) -> None:
        tracker = StepTracker()
        self.assertEqual(tracker.feed("Reading SSH credentials from key.txt automatically."), 0)
        self.assertEqual(tracker.feed("Upload complete. Starting deployment on Ubuntu; keep this window open."), 1)
        self.assertEqual(tracker.feed("[1/6] 配置国内软件源并安装 Docker、Compose、Python"), 2)
        self.assertEqual(tracker.feed("[3/6] 下载固定版本镜像"), 2)
        self.assertEqual(tracker.feed("[4/6] 启动 AstrBot、NapCat 并回填实际 Token"), 3)
        self.assertEqual(tracker.feed("[5/6] 安装 QQ 掉线守护进程"), 4)
        self.assertEqual(tracker.feed("[6/6] 导入人格、插件及模型配置"), 5)
        self.assertEqual(tracker.feed("NapCat/OneBot tokens and service URLs saved"), 6)
        self.assertEqual(tracker.feed("[1/6] 再次出现"), 6)
        tracker.finish(True)
        self.assertEqual(tracker.percent, 100)
        self.assertEqual(len(STEP_LABELS), 7)

    def test_failure_does_not_advance(self) -> None:
        tracker = StepTracker()
        tracker.finish(False)
        self.assertFalse(tracker.done)
        self.assertEqual(tracker.current, 0)
        self.assertEqual(tracker.percent, 0)


class LineBufferTests(unittest.TestCase):
    def test_crlf_lf_cr_and_trailing_cr(self) -> None:
        buffer = LineBuffer()
        self.assertEqual(buffer.feed("a\r\nb\nc\rd"), ["a", "b", "c"])
        self.assertEqual(buffer.feed("\r\ne"), ["d"])
        self.assertEqual(buffer.flush(), "e")

    def test_split_chunks(self) -> None:
        buffer = LineBuffer()
        self.assertEqual(buffer.feed("one\r"), [])
        self.assertEqual(buffer.feed("\ntwo\n"), ["one", "two"])

    def test_empty_lines(self) -> None:
        buffer = LineBuffer()
        self.assertEqual(buffer.feed("\n\nx\n"), ["", "", "x"])


class DecoderTests(unittest.TestCase):
    def test_split_multibyte_character(self) -> None:
        decoder = TextDecoder("utf-8")
        data = "中文".encode("utf-8")
        first = decoder.feed(data[:1])
        second = decoder.feed(data[1:])
        self.assertEqual(first + second, "中文")
        self.assertEqual(decoder.flush(), "")

    def test_ansi_strip(self) -> None:
        self.assertEqual(strip_ansi("\x1b[31m红色\x1b[0m"), "红色")


if __name__ == "__main__":
    unittest.main()
