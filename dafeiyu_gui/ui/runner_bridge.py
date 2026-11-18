"""把后台读取线程的回调转换为 Qt 信号。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PyQt5.QtCore import QObject, pyqtSignal

from dafeiyu_gui.backend.runner import ProcessOutcome, ProcessSession


class RunnerBridge(QObject):
    line = pyqtSignal(str)
    finished = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.session: ProcessSession | None = None

    def run(self, argv: Sequence[str], cwd: Path | str) -> None:
        if self.session is not None:
            raise RuntimeError("已有操作在运行")
        self.session = ProcessSession(
            argv,
            cwd,
            on_line=self.line.emit,
            on_finished=self.finished.emit,
        )
        self.session.start()

    def send_input(self, text: str) -> bool:
        session = self.session
        return bool(session and session.send_input(text))

    def cancel(self) -> None:
        if self.session is not None:
            self.session.cancel()

    @property
    def running(self) -> bool:
        return self.session is not None and not self.session.finished

    def clear_finished(self) -> None:
        self.session = None

    def wait(self, timeout: float | None = None) -> bool:
        return bool(self.session and self.session.wait(timeout))
