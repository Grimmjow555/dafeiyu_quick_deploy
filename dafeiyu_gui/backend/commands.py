"""把界面动作映射为 upload.ps1 的调用参数。

所有动作都只传开关和 upload.ps1 的绝对路径；SSH 密码和 API Key 从不进入
命令行，upload.ps1 自己从 key.txt 读取。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class ActionSpec:
    key: str
    title: str
    upload_args: tuple[str, ...] = ()
    long_running: bool = False
    needs_confirm: bool = False
    description: str = ""


ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        "deploy",
        "一键部署 / 更新",
        upload_args=(),
        long_running=True,
        needs_confirm=True,
        description="上传并执行部署，首次可能需要十几分钟",
    ),
    ActionSpec("status", "刷新状态", upload_args=("-Status",)),
    ActionSpec("start", "启动服务", upload_args=("-Start",)),
    ActionSpec("stop", "停止服务", upload_args=("-Stop",)),
    ActionSpec("sync_key", "同步 Token", upload_args=("-SyncKey",)),
    ActionSpec("sync_password", "同步密码兜底", upload_args=("-SyncPassword",)),
)

ACTIONS_BY_KEY: dict[str, ActionSpec] = {action.key: action for action in ACTIONS}


def powershell_executable() -> str | None:
    """优先使用 Windows PowerShell 5.1；upload.ps1 依赖 .NET Framework 编译器。"""
    found = shutil.which("powershell.exe")
    if found:
        return found
    return shutil.which("powershell")


def ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def build_inner_command(script_path: Path | str, arguments: Sequence[str]) -> str:
    quoted_script = ps_quote(str(script_path))
    pieces = [f"& {quoted_script}"]
    index = 0
    while index < len(arguments):
        argument = str(arguments[index])
        if argument in ("-StartArgs", "-StopArgs"):
            values = [str(value) for value in arguments[index + 1 :]]
            if values:
                array_literal = "@(" + ",".join(ps_quote(value) for value in values) + ")"
                pieces.append(argument)
                pieces.append(array_literal)
            else:
                pieces.append(argument)
            break
        if argument.startswith("-"):
            # PowerShell 参数名不能加引号，否则会被当成普通字符串。
            pieces.append(argument)
        else:
            pieces.append(ps_quote(argument))
        index += 1
    return (
        "$OutputEncoding=[Text.Encoding]::UTF8; "
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        + " ".join(pieces)
    )


def build_process_argv(script_path: Path | str, arguments: Sequence[str]) -> list[str]:
    shell = powershell_executable() or "powershell.exe"
    return [
        shell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        build_inner_command(script_path, arguments),
    ]


def make_start_args(no_wait: bool = False) -> list[str]:
    return ["--no-wait"] if no_wait else []


def make_stop_args(
    dry_run: bool = False,
    down: bool = False,
    timeout: int | None = None,
) -> list[str]:
    if timeout is not None and not 0 <= int(timeout) <= 3600:
        raise ValueError("停止超时应在 0 到 3600 秒之间")
    result: list[str] = []
    if dry_run:
        result.append("--dry-run")
    if down:
        result.append("--down")
    if timeout is not None:
        result.extend(["--timeout", str(int(timeout))])
    return result


def build_action_arguments(
    action_key: str,
    *,
    start_no_wait: bool = False,
    stop_dry_run: bool = False,
    stop_down: bool = False,
    stop_timeout: int | None = None,
) -> list[str]:
    try:
        action = ACTIONS_BY_KEY[action_key]
    except KeyError as exc:
        raise ValueError(f"未知动作：{action_key}") from exc
    arguments = list(action.upload_args)
    if action_key == "start":
        extra = make_start_args(start_no_wait)
        if extra:
            arguments.extend(["-StartArgs", *extra])
    elif action_key == "stop":
        extra = make_stop_args(stop_dry_run, stop_down, stop_timeout)
        if extra:
            arguments.extend(["-StopArgs", *extra])
    return arguments


def display_command(action_key: str, arguments: Sequence[str] | None = None) -> str:
    """给日志用的、不含任何凭证的命令展示。"""
    if arguments is None:
        arguments = build_action_arguments(action_key)
    quoted = []
    for argument in arguments:
        if argument and (argument.startswith("-") or _looks_like_value(argument)):
            quoted.append(argument)
        else:
            quoted.append(ps_quote(argument))
    suffix = (" " + " ".join(quoted)) if quoted else ""
    return f"upload.ps1{suffix}"


def _looks_like_value(argument: str) -> bool:
    return argument.isdigit()
