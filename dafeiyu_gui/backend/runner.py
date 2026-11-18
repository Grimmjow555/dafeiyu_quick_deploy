"""运行 upload.ps1 的纯 Python 子进程会话。

用 subprocess 而不是 QProcess，是为了可靠地隐藏 PowerShell 控制台窗口，
并且能直接向子进程的 stdin 写入主机密钥确认。读取放在后台线程里，界面通过
runner_bridge 转成 Qt 信号。
"""

from __future__ import annotations

import codecs
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class LineBuffer:
    """把任意分块文本切成行，兼容 CRLF、LF、CR 和跨块的 \\r\\n。"""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        lines: list[str] = []
        while True:
            index = -1
            width = 1
            for position, char in enumerate(self._buffer):
                if char == "\n":
                    index = position
                    width = 1
                    break
                if char == "\r":
                    if position + 1 >= len(self._buffer):
                        # 末尾单独的 \r 可能属于下一块 \r\n，先等一下。
                        return lines
                    index = position
                    width = 2 if self._buffer[position + 1] == "\n" else 1
                    break
            if index < 0:
                break
            lines.append(self._buffer[:index])
            self._buffer = self._buffer[index + width :]
        return lines

    def flush(self) -> str:
        remainder = self._buffer.strip("\r\n")
        self._buffer = ""
        return remainder


class TextDecoder:
    def __init__(self, encoding: str = "utf-8") -> None:
        self.encoding = encoding
        self._decoder = codecs.getincrementaldecoder(encoding)(errors="replace")

    def feed(self, data: bytes) -> str:
        return self._decoder.decode(data)

    def flush(self) -> str:
        return self._decoder.decode(b"", final=True)


@dataclass(frozen=True)
class ProcessOutcome:
    exit_code: int
    canceled: bool
    duration: float
    launch_error: str = ""


class ProcessSession:
    """单次子进程会话；回调都在读取线程中执行。"""

    def __init__(
        self,
        argv: Sequence[str],
        cwd: Path | str,
        on_line: Callable[[str], None],
        on_finished: Callable[[ProcessOutcome], None],
        *,
        env: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> None:
        self._argv = list(argv)
        self._cwd = Path(cwd)
        self._on_line = on_line
        self._on_finished = on_finished
        self._env = env
        self._encoding = encoding
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._canceled = False
        self._finished = threading.Event()
        self._started_at = 0.0
        self._launch_error = ""
        self._callback_error: BaseException | None = None

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    @property
    def pid(self) -> int | None:
        proc = self._proc
        return proc.pid if proc is not None else None

    @property
    def callback_error(self) -> BaseException | None:
        return self._callback_error

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("同一个会话不能启动两次")
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="dafeiyu-upload", daemon=True)
        self._thread.start()

    def wait(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    def send_input(self, text: str) -> bool:
        """向子进程 stdin 写一行（只用于主机密钥确认的 YES/空行）。"""
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None or proc.stdin is None:
            return False
        try:
            proc.stdin.write(text.encode("utf-8"))
            proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def cancel(self) -> None:
        self._canceled = True
        threading.Thread(target=self._kill_tree, name="dafeiyu-upload-cancel", daemon=True).start()

    def _kill_tree(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        if os.name == "nt":
            try:
                completed = subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if completed.returncode == 0:
                    return
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            proc.kill()
        except OSError:
            pass

    def _emit_line(self, line: str) -> None:
        try:
            self._on_line(line)
        except BaseException as exc:  # 回调异常不能拖死读取线程
            if self._callback_error is None:
                self._callback_error = exc

    def _finish(self, outcome: ProcessOutcome) -> None:
        self._finished.set()
        try:
            self._on_finished(outcome)
        except BaseException as exc:
            if self._callback_error is None:
                self._callback_error = exc

    def _run(self) -> None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        env = self._env if self._env is not None else os.environ.copy()
        proc: subprocess.Popen[bytes] | None = None
        exit_code = -1
        try:
            proc = subprocess.Popen(
                self._argv,
                cwd=str(self._cwd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                env=env,
                creationflags=creationflags,
            )
            with self._lock:
                self._proc = proc
            if self._canceled and proc.poll() is None:
                self._kill_tree()
            assert proc.stdout is not None
            fd = proc.stdout.fileno()
            decoder = TextDecoder(self._encoding)
            buffer = LineBuffer()
            while True:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                text = decoder.feed(chunk)
                for line in buffer.feed(text):
                    self._emit_line(strip_ansi(line))
            for line in buffer.feed(decoder.flush()):
                self._emit_line(strip_ansi(line))
            remainder = buffer.flush()
            if remainder:
                self._emit_line(strip_ansi(remainder))
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass
            exit_code = proc.wait()
        except FileNotFoundError as exc:
            self._launch_error = f"找不到可执行文件：{exc.filename or exc}"
            exit_code = -1
        except OSError as exc:
            self._launch_error = f"无法启动 PowerShell：{exc.strerror or exc}"
            exit_code = -1
        finally:
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
            if proc is not None:
                for stream in (proc.stdout, proc.stdin):
                    try:
                        if stream is not None:
                            stream.close()
                    except OSError:
                        pass
            duration = max(0.0, time.monotonic() - self._started_at)
            self._finish(
                ProcessOutcome(
                    exit_code=exit_code,
                    canceled=self._canceled,
                    duration=duration,
                    launch_error=self._launch_error,
                )
            )
