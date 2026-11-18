"""解析 start.sh --status / deploy.sh --check 的输出。

只做保守识别：认不出来就保持 unknown，界面显示“未知”，绝不把未确认的
服务或 QQ 状态说成正常。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from .runner import strip_ansi

_WATCHDOG_RE = re.compile(r"QQ 掉线守护：\s*(\S+)")
_WATCHDOG_RECORD_RE = re.compile(r"守护进程记录：\s*([A-Za-z_]+)")

WATCHDOG_LABELS = {
    "active": "运行中",
    "activating": "启动中",
    "inactive": "未运行",
    "failed": "启动失败",
    "deactivating": "停止中",
    "not_installed": "未安装",
    "unknown": "未知",
}

QQ_LABELS = {
    "online": "在线",
    "offline": "离线",
    "needs_qr": "等待扫码",
    "unknown": "未知",
}

SERVICE_LABELS = {
    "running": "运行中",
    "stopped": "已停止",
    "unknown": "未知",
}

WATCHDOG_STATUS_LABELS = {
    "online": "在线",
    "offline": "离线",
    "degraded": "连接异常",
    "needs_qr": "等待扫码",
    "awaiting_login": "等待首次扫码",
    "api_down": "WebUI 不可用",
    "api_error": "接口错误",
    "stopped": "已停机",
    "starting": "启动中",
    "config_error": "配置错误",
}


@dataclass
class StatusReport:
    services: str = "unknown"
    qq: str = "unknown"
    qq_detail: str = ""
    watchdog: str = "unknown"
    voice_enabled: bool | None = None
    voice_model: str = ""
    memory_enabled: bool | None = None
    plugins_active: int | None = None
    napcat_auth_limited: bool = False
    verification: dict | None = None
    checked_at: datetime | None = None
    raw: str = field(default="", repr=False)

    @property
    def services_label(self) -> str:
        return SERVICE_LABELS.get(self.services, "未知")

    @property
    def qq_label(self) -> str:
        return QQ_LABELS.get(self.qq, "未知")

    @property
    def watchdog_label(self) -> str:
        return WATCHDOG_LABELS.get(self.watchdog, "未知")


def _parse_verification(line: str, report: StatusReport) -> None:
    try:
        data = json.loads(line)
    except ValueError:
        return
    if not isinstance(data, dict) or "services_ready" not in data:
        return
    report.verification = data
    if data.get("services_ready") is True:
        report.services = "running"
    if isinstance(data.get("voice_enabled"), bool):
        report.voice_enabled = data["voice_enabled"]
    if isinstance(data.get("voice_model"), str):
        report.voice_model = data["voice_model"]
    if isinstance(data.get("memory_enabled"), bool):
        report.memory_enabled = data["memory_enabled"]
    if isinstance(data.get("plugins_active"), int):
        report.plugins_active = data["plugins_active"]
    if data.get("napcat_auth_limited") is True:
        report.napcat_auth_limited = True
    if isinstance(data.get("qq_watchdog_active"), bool):
        report.watchdog = "active" if data["qq_watchdog_active"] else "inactive"
    watchdog_status = data.get("qq_watchdog_status")
    if isinstance(watchdog_status, str) and watchdog_status:
        report.qq_detail = WATCHDOG_STATUS_LABELS.get(watchdog_status, watchdog_status)
        if watchdog_status == "online":
            report.qq = "online"
        elif watchdog_status in {"needs_qr", "awaiting_login"}:
            report.qq = "needs_qr"


def parse_status(text: str) -> StatusReport:
    report = StatusReport(raw=text)
    explicit_qq: str | None = None
    watchdog_record: str | None = None
    needs_qr = False
    for raw_line in text.splitlines():
        line = strip_ansi(raw_line).strip()
        if not line:
            continue
        if line.startswith("{") and '"services_ready"' in line:
            _parse_verification(line, report)
            continue
        if "大肥鱼正在运行" in line or "大肥鱼已启动" in line or "容器与守护进程已启动" in line:
            report.services = "running"
            continue
        if "大肥鱼当前未运行" in line or "大肥鱼已停止" in line:
            report.services = "stopped"
            continue
        watchdog_match = _WATCHDOG_RE.search(line)
        if watchdog_match:
            value = watchdog_match.group(1)
            if value in WATCHDOG_LABELS:
                report.watchdog = value
            elif value in {"active", "inactive", "failed"}:
                report.watchdog = value
            elif "未安装" in value:
                report.watchdog = "not_installed"
            continue
        record_match = _WATCHDOG_RECORD_RE.search(line)
        if record_match:
            watchdog_record = record_match.group(1)
            report.qq_detail = WATCHDOG_STATUS_LABELS.get(
                watchdog_record, report.qq_detail or watchdog_record
            )
            if watchdog_record in {"needs_qr", "awaiting_login"}:
                needs_qr = True
            continue
        if "QQ 状态：" in line:
            if "未在线" in line:
                explicit_qq = "offline"
            elif "在线" in line:
                explicit_qq = "online"
            continue
        if "等待扫码" in line or "等待首次扫码" in line:
            needs_qr = True
        if "needs_qr" in line or "awaiting_login" in line:
            needs_qr = True
        if "限流" in line or "rate limit" in line.lower():
            report.napcat_auth_limited = True
        if "QQ 已登录" in line:
            explicit_qq = "online"
        if "等待用户用机器人 QQ 扫码登录" in line:
            needs_qr = True
    if explicit_qq == "online" or report.qq == "online":
        report.qq = "online"
    elif needs_qr:
        report.qq = "needs_qr"
    elif explicit_qq == "offline":
        report.qq = "offline"
    if watchdog_record and not report.qq_detail:
        report.qq_detail = WATCHDOG_STATUS_LABELS.get(watchdog_record, watchdog_record)
    report.checked_at = datetime.now()
    return report
