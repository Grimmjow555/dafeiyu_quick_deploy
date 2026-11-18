"""总览页：状态卡片、后台链接、操作按钮、阶段进度和运行日志。"""

from __future__ import annotations

from datetime import datetime

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dafeiyu_gui.backend.status import StatusReport
from dafeiyu_gui.ui.widgets import (
    Banner,
    LogView,
    SectionCard,
    StatusBoard,
    StepIndicator,
)


class OverviewPage(QWidget):
    deploy_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    sync_key_requested = pyqtSignal()
    sync_password_requested = pyqtSignal()
    open_url_requested = pyqtSignal(str)
    terminal_requested = pyqtSignal()
    open_project_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._long_running = False
        self._qq_password_present = False
        self._urls: dict[str, str] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.banner = Banner()
        layout.addWidget(self.banner)

        self.status_board = StatusBoard()
        layout.addWidget(self.status_board)

        self._status_hint = QLabel("状态未知。点击「刷新状态」查询服务器（不会自动轮询，避免 NapCat 限流）。")
        self._status_hint.setObjectName("InlineNote")
        self._status_hint.setWordWrap(True)
        layout.addWidget(self._status_hint)

        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        url_title = QLabel("后台地址：")
        url_title.setObjectName("CardHint")
        url_row.addWidget(url_title)
        self._astrbot_button = QPushButton("AstrBot 后台")
        self._napcat_button = QPushButton("NapCat 扫码登录")
        self._astrbot_button.clicked.connect(lambda: self._open_url("AstrBot"))
        self._napcat_button.clicked.connect(lambda: self._open_url("NapCat"))
        url_row.addWidget(self._astrbot_button)
        url_row.addWidget(self._napcat_button)
        port_hint = QLabel("6185 / 6099 · 安全组需放行")
        port_hint.setObjectName("CardHint")
        url_row.addStretch(1)
        url_row.addWidget(port_hint)
        layout.addLayout(url_row)

        actions_card = SectionCard("操作")
        self.actions_card = actions_card
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.deploy_button = QPushButton("一键部署 / 更新")
        self.deploy_button.setObjectName("PrimaryButton")
        self.deploy_button.setMinimumHeight(42)
        self.refresh_button = QPushButton("刷新状态")
        self.start_button = QPushButton("启动服务")
        self.stop_button = QPushButton("停止服务…")
        self.sync_key_button = QPushButton("同步 Token")
        self.sync_password_button = QPushButton("同步密码兜底")
        self.terminal_button = QPushButton("SSH 终端")
        self.deploy_button.clicked.connect(self.deploy_requested)
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.start_button.clicked.connect(self.start_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.sync_key_button.clicked.connect(self.sync_key_requested)
        self.sync_password_button.clicked.connect(self.sync_password_requested)
        self.terminal_button.clicked.connect(self.terminal_requested)
        self.refresh_button.setToolTip("执行 upload.ps1 -Status（快捷键 F5）")
        grid.addWidget(self.deploy_button, 0, 0, 1, 2)
        grid.addWidget(self.refresh_button, 0, 2)
        grid.addWidget(self.start_button, 0, 3)
        grid.addWidget(self.stop_button, 1, 0)
        grid.addWidget(self.sync_key_button, 1, 1)
        grid.addWidget(self.sync_password_button, 1, 2)
        grid.addWidget(self.terminal_button, 1, 3)
        grid.setColumnStretch(0, 2)
        actions_card.body.addLayout(grid)
        action_hint_row = QHBoxLayout()
        self._action_hint = QLabel(
            "停止不会删除 data/、napcat/；停止后 QQ 离线，下次启动可能需要快速登录或扫码。"
        )
        self._action_hint.setObjectName("CardHint")
        self._action_hint.setWordWrap(True)
        action_hint_row.addWidget(self._action_hint, 1)
        self.open_folder_button = QPushButton("打开项目目录")
        self.open_folder_button.setObjectName("LinkButton")
        self.open_folder_button.clicked.connect(self.open_project_requested)
        action_hint_row.addWidget(self.open_folder_button)
        actions_card.body.addLayout(action_hint_row)
        layout.addWidget(actions_card)

        self.progress_panel = QFrame()
        self.progress_panel.setObjectName("ProgressPanel")
        progress_layout = QVBoxLayout(self.progress_panel)
        progress_layout.setContentsMargins(16, 12, 16, 12)
        progress_layout.setSpacing(8)
        progress_top = QHBoxLayout()
        self._progress_label = QLabel("")
        self._progress_label.setObjectName("CardTitle")
        self._progress_label.setWordWrap(True)
        self._elapsed_label = QLabel("")
        self._elapsed_label.setObjectName("CardHint")
        progress_top.addWidget(self._progress_label, 1)
        progress_top.addWidget(self._elapsed_label)
        progress_layout.addLayout(progress_top)
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        progress_layout.addWidget(self._progress_bar)
        self.step_indicator = StepIndicator()
        progress_layout.addWidget(self.step_indicator)
        progress_bottom = QHBoxLayout()
        self._progress_hint = QLabel("日志会实时显示；遇到主机密钥变化时会暂停并请你确认。")
        self._progress_hint.setObjectName("CardHint")
        self._progress_hint.setWordWrap(True)
        progress_bottom.addWidget(self._progress_hint, 1)
        self.cancel_button = QPushButton("取消当前操作")
        self.cancel_button.setObjectName("DangerButton")
        self.cancel_button.clicked.connect(self.cancel_requested)
        progress_bottom.addWidget(self.cancel_button)
        progress_layout.addLayout(progress_bottom)
        self.progress_panel.hide()
        layout.addWidget(self.progress_panel)

        self.log_view = LogView()
        self.log_view.setMinimumHeight(180)
        layout.addWidget(self.log_view, 1)

        self.set_available({})

    def set_server(self, text: str) -> None:
        self.setWindowTitle(text)

    def show_banner(self, text: str, level: str = "info") -> None:
        self.banner.show_message(text, level)

    def hide_banner(self) -> None:
        self.banner.hide_banner()

    def set_available(self, available: dict[str, bool]) -> None:
        mapping = {
            "deploy": self.deploy_button,
            "refresh": self.refresh_button,
            "start": self.start_button,
            "stop": self.stop_button,
            "sync_key": self.sync_key_button,
            "sync_password": self.sync_password_button,
            "terminal": self.terminal_button,
        }
        for key, button in mapping.items():
            button.setEnabled(bool(available.get(key, False)) and not self._busy)
        self.open_folder_button.setEnabled(True)

    def set_qq_password_present(self, present: bool) -> None:
        self._qq_password_present = present
        if present:
            self.sync_password_button.setToolTip(
                "执行 upload.ps1 -SyncPassword：把 QQ.txt 同步到服务器密码兜底文件（内容不会显示）。"
            )
        else:
            self.sync_password_button.setToolTip(
                "项目目录没有 QQ.txt；按 README 第 4 节创建后即可启用密码兜底。"
            )

    def set_urls(self, urls: dict[str, str]) -> None:
        self._urls = dict(urls)
        for key, button in (("AstrBot", self._astrbot_button), ("NapCat", self._napcat_button)):
            url = self._urls.get(key, "")
            button.setEnabled(bool(url))
            button.setToolTip(url or "key.txt 中还没有有效的 SSH_HOST")

    def _open_url(self, key: str) -> None:
        url = self._urls.get(key)
        if url:
            self.open_url_requested.emit(url)

    def apply_local_config(self, values: dict[str, str]) -> None:
        self.status_board.apply_local_config(values)

    def apply_report(self, report: StatusReport) -> None:
        self.status_board.apply_report(report)
        checked = report.checked_at or datetime.now()
        suffix = "（NapCat 接口限流，状态可能来自守护进程）" if report.napcat_auth_limited else ""
        self._status_hint.setText(f"最近检查：{checked:%H:%M:%S}{suffix}")

    def reset_status(self) -> None:
        self.status_board.reset_local()
        self._status_hint.setText(
            "状态未知。点击「刷新状态」查询服务器（不会自动轮询，避免 NapCat 限流）。"
        )

    def begin_operation(self, title: str, long_running: bool) -> None:
        self._busy = True
        self._long_running = long_running
        self.actions_card.hide()
        self.progress_panel.show()
        self._progress_label.setText(f"正在执行：{title}")
        self._progress_hint.setText(
            "日志会实时显示；遇到主机密钥变化时会暂停并请你确认。"
        )
        self._elapsed_label.setText("已用时 00:00")
        self.cancel_button.setEnabled(True)
        if long_running:
            self.step_indicator.show()
            self.step_indicator.reset()
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(0)
        else:
            self.step_indicator.hide()
            self._progress_bar.setRange(0, 0)
        self.set_available({})

    def update_step(self, current: int, percent: int, done: bool = False) -> None:
        if not self._long_running:
            return
        self.step_indicator.set_current(current, done=done)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(percent)

    def set_elapsed(self, seconds: int) -> None:
        minutes, secs = divmod(max(0, int(seconds)), 60)
        self._elapsed_label.setText(f"已用时 {minutes:02d}:{secs:02d}")

    def set_progress_detail(self, text: str) -> None:
        self._progress_hint.setText(text)

    def finish_operation(self, success: bool, message: str) -> None:
        self._busy = False
        self._progress_label.setText(message)
        if self._long_running:
            self.step_indicator.set_current(6, done=success)
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(100 if success else self._progress_bar.value())
        else:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(100 if success else 0)
        self.cancel_button.setEnabled(False)
        self.progress_panel.hide()
        self.actions_card.show()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if not busy:
            return
        self.set_available({})

    def append_log(self, text: str, kind: str = "normal") -> None:
        self.log_view.append_line(text, kind)

    def append_separator(self, title: str) -> None:
        self.log_view.append_separator(title)

    def append_footer(self, text: str, success: bool) -> None:
        self.log_view.append_footer(text, success)
