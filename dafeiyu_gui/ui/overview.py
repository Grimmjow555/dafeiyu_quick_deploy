"""总览页：状态卡片、后台链接、操作按钮、阶段进度和运行日志。"""

from __future__ import annotations

from datetime import datetime

from PyQt5.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dafeiyu_gui.backend.status import StatusReport
from dafeiyu_gui.ui import icons
from dafeiyu_gui.ui.widgets import (
    MAX_CONTENT_WIDTH,
    Banner,
    LogView,
    ResultBar,
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
        self._urls: dict[str, str] = {}
        self._icon_buttons: list[tuple[QPushButton, str, str]] = []
        self._user_moved_splitter = False
        self._fitting = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        wrap = QHBoxLayout(container)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(0)
        self.content = QWidget()
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.content.setMaximumWidth(MAX_CONTENT_WIDTH)
        layout = QVBoxLayout(self.content)
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
        url_row.addStretch(1)
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
        self.stop_button.setObjectName("DangerButton")
        self.sync_key_button = QPushButton("同步 Token")
        self.sync_password_button = QPushButton("同步密码兜底")
        self.terminal_button = QPushButton("SSH 终端")
        for button in (self.sync_key_button, self.sync_password_button, self.terminal_button):
            button.setObjectName("SubtleButton")
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

        self.result_bar = ResultBar()
        layout.addWidget(self.result_bar)
        layout.addStretch(1)

        wrap.addStretch(1)
        wrap.addWidget(self.content, 1000)
        wrap.addStretch(1)
        scroll.setWidget(container)

        self.log_view = LogView()
        self.log_view.setMinimumHeight(120)
        self.log_view.setMaximumWidth(MAX_CONTENT_WIDTH)
        log_container = QWidget()
        log_row = QHBoxLayout(log_container)
        log_row.setContentsMargins(0, 0, 0, 0)
        log_row.setSpacing(0)
        log_row.addStretch(1)
        log_row.addWidget(self.log_view, 1000)
        log_row.addStretch(1)

        self.splitter.addWidget(scroll)
        self.splitter.addWidget(log_container)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([470, 200])
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        outer.addWidget(self.splitter)

        self._icon_buttons = [
            (self.deploy_button, "deploy", "on_primary"),
            (self.refresh_button, "refresh", "muted"),
            (self.start_button, "play", "muted"),
            (self.stop_button, "stop", "danger"),
            (self.sync_key_button, "key", "muted"),
            (self.sync_password_button, "lock", "muted"),
            (self.terminal_button, "terminal", "muted"),
            (self.open_folder_button, "folder", "muted"),
        ]
        self.set_available({})

    # ---------------- 图标 / 链接 ----------------

    def apply_icons(self, colors: dict[str, str]) -> None:
        for button, name, role in self._icon_buttons:
            button.setIcon(icons.icon(name, icons.resolve(role, colors)))
            button.setIconSize(QSize(16, 16))

    def show_banner(self, text: str, level: str = "info") -> None:
        self.banner.show_message(text, level)
        self._schedule_fit()

    def hide_banner(self) -> None:
        self.banner.hide_banner()
        self._schedule_fit()

    # ---------------- 上下两个面板的高度 ----------------

    def _on_splitter_moved(self, *_args) -> None:
        if not self._fitting:
            self._user_moved_splitter = True

    def _schedule_fit(self) -> None:
        QTimer.singleShot(0, self._fit_top_pane)

    def _fit_top_pane(self) -> None:
        """让上方面板贴合内容高度，避免把按钮行切成两半。

        用户手动拖过一次分割条之后就不再自动调整。
        """
        if self._user_moved_splitter:
            return
        total = sum(self.splitter.sizes())
        if total <= 0:
            return
        ideal = self.content.sizeHint().height()
        log_min = 140
        top = max(200, min(ideal, total - log_min))
        self._fitting = True
        try:
            self.splitter.setSizes([top, total - top])
        finally:
            self._fitting = False

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        self._schedule_fit()

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
            button.setToolTip(
                f"{url}\n端口 6185 / 6099，云安全组需要放行。" if url else "key.txt 中还没有有效的 SSH_HOST"
            )

    def _open_url(self, key: str) -> None:
        url = self._urls.get(key)
        if url:
            self.open_url_requested.emit(url)

    # ---------------- 状态 ----------------

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

    def mark_stopped(self) -> None:
        """停止命令完成后同步卡片与检查时间，避免两者不一致。"""
        self.status_board.mark_stopped()
        self._status_hint.setText(f"最近检查：{datetime.now():%H:%M:%S}（本地停止操作）")

    # ---------------- 操作过程 ----------------

    def begin_operation(self, title: str, long_running: bool) -> None:
        self._busy = True
        self._long_running = long_running
        self.result_bar.clear()
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
        sizes = self.splitter.sizes()
        if len(sizes) == 2 and sizes[1] < 160:
            self.splitter.setSizes([max(200, sizes[0] - 60), 160])
        self.set_available({})
        self._schedule_fit()

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

    def finish_operation(self, success: bool, message: str, level: str = "") -> None:
        self._busy = False
        if not level:
            level = "success" if success else "error"
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
        # 结果放在独立的 ResultBar 里：进度面板收起后用户仍然看得到结论。
        if message:
            self.result_bar.show_result(message, level)
        self._schedule_fit()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if not busy:
            return
        self.set_available({})

    # ---------------- 日志 ----------------

    def append_log(self, text: str, kind: str = "normal") -> None:
        self.log_view.append_line(text, kind)

    def append_separator(self, title: str) -> None:
        self.log_view.append_separator(title)

    def append_footer(self, text: str, success: bool) -> None:
        self.log_view.append_footer(text, success)
