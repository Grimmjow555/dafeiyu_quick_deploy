"""主窗口：导航、动作编排、日志、主机密钥确认和退出保护。"""

from __future__ import annotations

import re
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QShortcut,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from dafeiyu_gui import APP_NAME, __version__
from dafeiyu_gui.backend import commands, keyfile
from dafeiyu_gui.backend.keyfile import (
    KeyDocument,
    KeyFileError,
    ValidationIssue,
    missing_required,
    qq_password_file_path,
    service_urls,
    validate_values,
    write_key_file,
)
from dafeiyu_gui.backend.redact import Redactor
from dafeiyu_gui.backend.runner import ProcessOutcome, strip_ansi
from dafeiyu_gui.backend.status import StatusReport, parse_status
from dafeiyu_gui.backend.steps import StepTracker
from dafeiyu_gui.ui import dialogs, icons, theme
from dafeiyu_gui.ui.help_page import HelpPage
from dafeiyu_gui.ui.overview import OverviewPage
from dafeiyu_gui.ui.runner_bridge import RunnerBridge
from dafeiyu_gui.ui.settings_page import SettingsPage
from dafeiyu_gui.ui.widgets import MAX_CONTENT_WIDTH, open_local_path

_ERROR_RE = re.compile(
    r"(?i)(错误|失败|error|failed|traceback|exception|denied|refused|无法|timed out|超时)"
)
_WARN_RE = re.compile(r"(?i)(警告|warning|warn|注意|提示[:：])")
_SUCCESS_RE = re.compile(r"(完成|成功|已启动|已停止|已部署|已保存|已同步|已启用)")


class MainWindow(QMainWindow):
    # 顶栏只显示"当前页面"，不再和侧栏品牌重复。
    _PAGE_META: tuple[tuple[str, str], ...] = (
        ("总览", "状态、后台入口与运行日志"),
        ("配置", "字段与 key.txt 一致，保存保留注释与顺序"),
        ("帮助", "图形界面只是 upload.ps1 的封装，命令行始终可用"),
    )

    def __init__(
        self,
        project_root: Path,
        qsettings: QSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.script_path = self.project_root / "upload.ps1"
        self.key_path = self.project_root / "key.txt"
        self.qsettings = qsettings
        self.doc: KeyDocument | None = None
        self.status_report = StatusReport()
        self.redactor = Redactor()
        self.bridge: RunnerBridge | None = None
        self._action_key: str | None = None
        self._action_meta: dict = {}
        self._busy = False
        self._finishing = False
        self._current_output: list[str] = []
        self._raw_tail: deque[str] = deque(maxlen=160)
        self._step_tracker = StepTracker()
        self._host_prompt_scheduled = False
        self._host_canceled = False
        self._started_at = 0.0
        self._last_output_at = 0.0
        self._quiet_notified = False
        self._theme_name = str(self.qsettings.value("theme", "light") or "light")
        if self._theme_name not in theme.THEMES:
            self._theme_name = "light"
        self._config_error = ""
        self._closing = False

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(900, 620)
        self.resize(1180, 820)
        self.setWindowIcon(QApplication.windowIcon())
        self._build_ui()
        self._apply_icons(theme.THEMES[self._theme_name])
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._select_page(int(self.qsettings.value("page", 0) or 0), persist=False)
        self._load_config(initial=True)
        self._restore_geometry()

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(208)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 14)
        sidebar_layout.setSpacing(6)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(9)
        logo = QLabel()
        logo.setPixmap(self.windowIcon().pixmap(38, 38))
        logo.setFixedSize(38, 38)
        brand_row.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel("大肥鱼")
        name.setObjectName("AppTitle")
        brand_text.addWidget(name)
        sub = QLabel("本地部署控制台")
        sub.setObjectName("AppSubtitle")
        brand_text.addWidget(sub)
        brand_row.addLayout(brand_text)
        brand_row.addStretch(1)
        sidebar_layout.addLayout(brand_row)
        sidebar_layout.addSpacing(18)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        for index, (text, _subtitle) in enumerate(self._PAGE_META):
            button = QPushButton(text)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index: self._select_page(i))
            self._nav_group.addButton(button, index)
            self._nav_buttons.append(button)
            sidebar_layout.addWidget(button)
        sidebar_layout.addStretch(1)
        about = QPushButton("关于 / 版本")
        about.setObjectName("LinkButton")
        about.clicked.connect(self._show_about)
        sidebar_layout.addWidget(about)
        version = QLabel(f"v{__version__}")
        version.setObjectName("Subtle")
        sidebar_layout.addWidget(version)
        outer.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 14, 18, 10)
        content_layout.setSpacing(12)
        header = QFrame()
        header.setObjectName("Header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 10)
        header_layout.setSpacing(10)
        heading = QVBoxLayout()
        heading.setSpacing(0)
        self.page_title = QLabel(self._PAGE_META[0][0])
        self.page_title.setObjectName("PageTitle")
        heading.addWidget(self.page_title)
        self.page_subtitle = QLabel(self._PAGE_META[0][1])
        self.page_subtitle.setObjectName("AppSubtitle")
        heading.addWidget(self.page_subtitle)
        header_layout.addLayout(heading)
        header_layout.addStretch(1)
        self.server_chip = QLabel("未配置服务器")
        self.server_chip.setObjectName("ServerChip")
        header_layout.addWidget(self.server_chip)
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("LinkButton")
        self.theme_button.clicked.connect(self._toggle_theme)
        self._update_theme_button()
        header_layout.addWidget(self.theme_button)
        header.setMaximumWidth(MAX_CONTENT_WIDTH)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(0)
        header_row.addStretch(1)
        header_row.addWidget(header, 1000)
        header_row.addStretch(1)
        content_layout.addLayout(header_row)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Pages")
        self.overview = OverviewPage()
        self.settings_page = SettingsPage()
        self.help_page = HelpPage()
        self.stack.addWidget(self.overview)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.help_page)
        content_layout.addWidget(self.stack, 1)
        outer.addWidget(content, 1)

        self.overview.deploy_requested.connect(lambda: self._request_action("deploy"))
        self.overview.refresh_requested.connect(lambda: self._request_action("status"))
        self.overview.start_requested.connect(lambda: self._request_action("start"))
        self.overview.stop_requested.connect(lambda: self._request_action("stop"))
        self.overview.sync_key_requested.connect(lambda: self._request_action("sync_key"))
        self.overview.sync_password_requested.connect(lambda: self._request_action("sync_password"))
        self.overview.terminal_requested.connect(self._open_terminal)
        self.overview.open_url_requested.connect(self._open_url)
        self.overview.open_project_requested.connect(self._open_project)
        self.overview.cancel_requested.connect(self._cancel_action)

        self.settings_page.save_requested.connect(self._on_save_clicked)
        self.settings_page.reload_requested.connect(self._on_reload_clicked)
        self.settings_page.open_key_file_requested.connect(self._open_key_file)
        self.settings_page.open_project_requested.connect(self._open_project)
        self.settings_page.sync_password_requested.connect(lambda: self._request_action("sync_password"))
        self.settings_page.dirty_changed.connect(self._on_dirty_changed)

        self.help_page.open_readme_requested.connect(self._open_readme)
        self.help_page.open_project_requested.connect(self._open_project)

        refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        refresh_shortcut.activated.connect(lambda: self._request_action("status"))
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self._request_save)
        quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        quit_shortcut.activated.connect(self.close)

        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("就绪")
        self.overview.log_view.append_line(
            "尚未运行操作。打开「配置」检查 key.txt，然后点击「一键部署 / 更新」。", "muted"
        )

    def _select_page(self, index: int, persist: bool = True) -> None:
        index = max(0, min(index, self.stack.count() - 1))
        self.stack.setCurrentIndex(index)
        for position, button in enumerate(self._nav_buttons):
            button.setChecked(position == index)
        title, subtitle = self._PAGE_META[index]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        if persist:
            self.qsettings.setValue("page", index)

    def _apply_icons(self, colors: dict[str, str]) -> None:
        nav_icons = ("grid", "sliders", "help")
        for button, name in zip(self._nav_buttons, nav_icons):
            button.setIcon(
                icons.toggle_icon(name, colors["muted"], colors["primary"])
            )
            button.setIconSize(QSize(16, 16))
        self.overview.apply_icons(colors)

    def _update_theme_button(self) -> None:
        self.theme_button.setText("深色模式" if self._theme_name == "light" else "浅色模式")

    def _toggle_theme(self) -> None:
        self._theme_name = "dark" if self._theme_name == "light" else "light"
        colors = theme.apply_theme(QApplication.instance(), self._theme_name)
        self.qsettings.setValue("theme", self._theme_name)
        self._update_theme_button()
        self._apply_icons(colors)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于",
            f"{APP_NAME} v{__version__}\n\n"
            "这是 upload.ps1 的本地图形封装，不会改变服务器端脚本。\n"
            "命令行部署方式始终可用；QQ 登录和主机密钥确认仍需用户本人完成。",
        )

    # ---------------- config ----------------

    def _load_config(self, initial: bool = False, quiet: bool = False) -> None:
        old_host = self.doc.get("SSH_HOST") if self.doc else None
        try:
            doc = keyfile.read_key_file(self.key_path)
        except KeyFileError as exc:
            self.doc = None
            self.redactor = Redactor()
            self.status_report = StatusReport()
            self._config_error = str(exc)
            self.settings_page.load_document(None)
            self.overview.set_urls({})
            self.overview.reset_status()
            self._set_server_chip(None)
            self._update_actions()
            self._refresh_config_banner()
            if not quiet:
                self.statusBar().showMessage(self._config_error, 8000)
            return
        self.doc = doc
        self._config_error = ""
        self.redactor = Redactor(doc.values)
        new_host = doc.get("SSH_HOST")
        if old_host is not None and new_host != old_host:
            self.status_report = StatusReport()
            self.overview.reset_status()
        self.settings_page.load_document(doc)
        self._update_local_display(doc)
        self._update_actions()
        if not quiet:
            self.statusBar().showMessage(
                "配置已载入" if not initial else "就绪", 5000
            )

    def _update_local_display(self, doc: KeyDocument) -> None:
        values = doc.values
        self._set_server_chip(values)
        self.overview.set_urls(service_urls(values))
        if self.status_report.verification is None:
            self.overview.apply_local_config(values)
        self.overview.set_qq_password_present(qq_password_file_path(self.project_root).is_file())
        self.settings_page.set_qq_password_present(
            qq_password_file_path(self.project_root).is_file(),
            qq_password_file_path(self.project_root),
        )
        if doc.parse_errors:
            self.settings_page.set_validation_issues(
                [ValidationIssue("", message) for message in doc.parse_errors]
            )
        else:
            self.settings_page.set_validation_issues(validate_values(values))
        self._refresh_config_banner()

    def _refresh_config_banner(self) -> None:
        if not self.script_path.is_file():
            self.overview.show_banner(
                "未找到 upload.ps1。请从项目根目录运行图形界面，或把文件放回原位置。", "error"
            )
            return
        if self.doc is None:
            self.overview.show_banner(
                self._config_error or "未找到 key.txt，请先按 README 创建配置文件。", "error"
            )
            return
        if self.doc.parse_errors:
            self.overview.show_banner(
                "key.txt 存在格式问题：" + "；".join(self.doc.parse_errors[:3]),
                "error",
            )
            return
        values = self.doc.values
        issues = validate_values(values)
        format_errors = [i for i in issues if i.field not in missing_required(values)]
        missing = missing_required(values)
        if format_errors:
            self.overview.show_banner(
                "请先修正配置项：" + "；".join(i.message for i in format_errors[:3]), "error"
            )
        elif missing:
            self.overview.show_banner(
                "配置不完整，部署前需要填写：" + "、".join(missing), "warn"
            )
        else:
            self.overview.hide_banner()

    def _set_server_chip(self, values: dict[str, str] | None) -> None:
        if not values:
            self.server_chip.setText("未配置服务器")
            self.server_chip.setToolTip("")
            self.setWindowTitle(APP_NAME)
            return
        host = values.get("SSH_HOST", "")
        user = values.get("SSH_USER", "")
        if host:
            text = f"{user}@{host}" if user else host
            self.server_chip.setText(text)
            self.server_chip.setToolTip(f"SSH {user}@{host}:22")
            self.setWindowTitle(f"{APP_NAME} - {text}")
        else:
            self.server_chip.setText("未配置服务器")
            self.server_chip.setToolTip("")
            self.setWindowTitle(APP_NAME)

    def _can_ssh(self) -> bool:
        if self.doc is None or self.doc.parse_errors:
            return False
        values = self.doc.values
        return bool(
            values.get("SSH_HOST")
            and values.get("SSH_USER")
            and values.get("SSH_PASSWORD")
            and service_urls(values)
        )

    def _update_actions(self) -> None:
        busy = self._busy
        can_ssh = self._can_ssh()
        script_ok = self.script_path.is_file()
        qq_present = qq_password_file_path(self.project_root).is_file()
        issues: list[ValidationIssue] = []
        missing: list[str] = []
        if self.doc is not None and not self.doc.parse_errors:
            issues = validate_values(self.doc.values)
            missing = missing_required(self.doc.values)
        deploy_ready = script_ok and can_ssh and not issues
        available = {
            "deploy": deploy_ready and not busy,
            "refresh": can_ssh and script_ok and not busy,
            "start": can_ssh and script_ok and not busy,
            "stop": can_ssh and script_ok and not busy,
            "sync_key": can_ssh and script_ok and not busy,
            "sync_password": can_ssh and script_ok and qq_present and not busy,
            "terminal": can_ssh and script_ok and not busy,
        }
        self.overview.set_available(available)
        self.settings_page.set_busy(busy)
        self.settings_page.set_save_enabled(
            not busy and self.doc is not None and not self.doc.parse_errors
        )
        self.settings_page.set_sync_password_enabled(can_ssh and script_ok and not busy)
        if not script_ok:
            self.overview.deploy_button.setToolTip("缺少 upload.ps1")
        elif missing:
            self.overview.deploy_button.setToolTip("缺少必填字段：" + "、".join(missing))
        elif issues:
            self.overview.deploy_button.setToolTip(issues[0].message)
        else:
            self.overview.deploy_button.setToolTip(
                "上传并执行 upload.ps1（首次可能需要十几分钟）"
            )

    def _on_dirty_changed(self, dirty: bool) -> None:
        if dirty:
            self.statusBar().showMessage("配置有未保存的修改", 3000)
        self.settings_page.set_save_enabled(
            not self._busy and self.doc is not None and not self.doc.parse_errors
        )

    def _on_save_clicked(self) -> None:
        if self._save_config(show_message=True):
            self.statusBar().showMessage("已保存 key.txt；重新部署后生效", 5000)

    def _request_save(self) -> None:
        """Ctrl+S：没有未保存修改时只提示，不重复写盘。"""
        if self.doc is None:
            self._select_page(1)
            dialogs.show_error(self, "无法保存", "key.txt 还未成功载入。")
            return
        if not self.settings_page.is_dirty():
            self.statusBar().showMessage("没有需要保存的修改", 3000)
            return
        self._on_save_clicked()

    def _save_config(self, show_message: bool = True) -> bool:
        if self.doc is None:
            dialogs.show_error(self, "无法保存", "key.txt 还未成功载入。")
            return False
        if not self._ensure_key_current():
            return False
        values = self.settings_page.values()
        issues = validate_values(values)
        missing = set(missing_required(values))
        format_errors = [issue for issue in issues if issue.field not in missing]
        self.settings_page.set_validation_issues(issues)
        if format_errors:
            message = "；".join(issue.message for issue in format_errors[:4])
            dialogs.show_error(self, "配置格式有误", "请先修正高亮字段：\n" + message)
            return False
        try:
            new_doc = write_key_file(self.doc, values)
        except KeyFileError as exc:
            dialogs.show_error(self, "保存 key.txt 失败", str(exc))
            return False
        old_host = self.doc.get("SSH_HOST")
        self.doc = new_doc
        self.redactor.refresh(new_doc.values)
        self.settings_page.load_document(new_doc)
        self._update_local_display(new_doc)
        if old_host != new_doc.get("SSH_HOST"):
            self.status_report = StatusReport()
            self.overview.reset_status()
            self.overview.apply_local_config(new_doc.values)
        self._update_actions()
        if show_message:
            if missing_required(new_doc.values):
                self.settings_page.set_validation_issues(validate_values(new_doc.values))
            else:
                self.settings_page.mark_saved_message("已保存 key.txt；重新部署后生效。")
        return True

    def _on_reload_clicked(self) -> None:
        if self.settings_page.is_dirty():
            if not dialogs.ask_reload_discard(self, "要放弃当前未保存的修改并重新载入吗？"):
                return
        self._load_config(quiet=True)
        self.statusBar().showMessage("已重新载入 key.txt", 4000)

    def _ensure_key_current(self) -> bool:
        """确认磁盘上的 key.txt 没有被外部修改。返回 False 表示当前操作应中止。"""
        if self.doc is None:
            return False
        try:
            stat = self.key_path.stat()
        except OSError:
            self._load_config(quiet=True)
            dialogs.show_error(self, "key.txt 不存在", "配置文件已被移动或删除，请重新载入。")
            return False
        if stat.st_mtime_ns == self.doc.mtime_ns and stat.st_size == self.doc.size:
            return True
        if self.settings_page.is_dirty():
            if not dialogs.ask_reload_discard(
                self, "key.txt 已被其他程序修改，当前表单还有未保存内容。"
            ):
                return False
            self._load_config(quiet=True)
            return False
        self._load_config(quiet=True)
        self.statusBar().showMessage("key.txt 已变化，已重新载入", 4000)
        return True

    # ---------------- actions ----------------

    def _request_action(self, action_key: str) -> None:
        if self._busy:
            return
        if action_key not in commands.ACTIONS_BY_KEY:
            return
        if not self.script_path.is_file():
            dialogs.show_error(self, "缺少 upload.ps1", "未在项目根目录找到 upload.ps1。")
            return
        if self.doc is None or self.doc.parse_errors:
            dialogs.show_error(
                self, "配置不可用", "key.txt 缺失或存在格式错误，请先在「配置」页修正。"
            )
            self._select_page(1)
            return
        if not self._ensure_key_current():
            return
        if self.settings_page.is_dirty():
            if not dialogs.ask_save_before_action(self):
                return
            if not self._save_config(show_message=False):
                return
        if not self._can_ssh():
            dialogs.show_error(
                self,
                "配置不完整",
                "开始前需要填写 SSH_HOST、SSH_USER、SSH_PASSWORD；请到「配置」页补全。",
            )
            self._select_page(1)
            return
        if action_key == "deploy":
            issues = validate_values(self.doc.values) if self.doc else []
            if issues:
                message = "；".join(issue.message for issue in issues[:4])
                dialogs.show_error(self, "配置不完整", message)
                self._select_page(1)
                return
            host = self.doc.get("SSH_HOST")
            if not dialogs.confirm_deploy(self, host):
                return
        meta: dict = {}
        if action_key == "stop":
            dialog = dialogs.StopOptionsDialog(self)
            if dialog.exec_() != dialog.Accepted:
                return
            dry_run, down, timeout = dialog.options()
            meta = {"dry_run": dry_run, "down": down, "timeout": timeout}
        if action_key == "sync_password":
            if not qq_password_file_path(self.project_root).is_file():
                dialogs.show_error(
                    self, "没有 QQ.txt", "项目目录没有 QQ.txt，无法同步密码兜底。"
                )
                return
        self._begin_action(action_key, meta)

    def _begin_action(self, action_key: str, meta: dict) -> None:
        spec = commands.ACTIONS_BY_KEY[action_key]
        arguments = commands.build_action_arguments(
            action_key,
            stop_dry_run=bool(meta.get("dry_run")),
            stop_down=bool(meta.get("down")),
            stop_timeout=meta.get("timeout"),
        )
        argv = commands.build_process_argv(self.script_path, arguments)
        self._action_key = action_key
        self._action_meta = dict(meta)
        self._busy = True
        self._finishing = False
        self._host_prompt_scheduled = False
        self._host_canceled = False
        self._current_output = []
        self._raw_tail.clear()
        self._step_tracker.reset()
        self._quiet_notified = False
        self._started_at = time.monotonic()
        self._last_output_at = self._started_at
        self._elapsed_timer.start()
        self.overview.begin_operation(spec.title, spec.long_running)
        self.overview.append_separator(spec.title)
        self.overview.append_log(
            "$ " + commands.display_command(action_key, arguments), "muted"
        )
        if action_key == "stop" and meta.get("dry_run"):
            self.overview.append_log("（--dry-run 预览模式：不会改动服务器）", "warn")
        self._update_actions()
        self.statusBar().showMessage(f"正在执行：{spec.title}")
        bridge = RunnerBridge(self)
        bridge.line.connect(self._on_output)
        bridge.finished.connect(self._on_process_finished)
        self.bridge = bridge
        try:
            bridge.run(argv, self.project_root)
        except Exception as exc:  # noqa: BLE001 - 启动失败要反馈到界面
            self._finish_with_launch_error(str(exc))

    def _finish_with_launch_error(self, message: str) -> None:
        self._current_output.append(message)
        self.overview.append_log(message, "error")
        outcome = ProcessOutcome(exit_code=-1, canceled=False, duration=0.0, launch_error=message)
        self._on_process_finished(outcome)

    def _on_output(self, line: str) -> None:
        if self._closing:
            return
        self._last_output_at = time.monotonic()
        self._quiet_notified = False
        self._raw_tail.append(line)
        self._current_output.append(line)
        if len(self._current_output) > 100000:
            del self._current_output[:20000]
        if self._action_key == "deploy":
            current = self._step_tracker.feed(line)
            self.overview.update_step(current, self._step_tracker.percent)
        if not self._host_prompt_scheduled and "The saved key differs" in line:
            self._host_prompt_scheduled = True
            QTimer.singleShot(0, self._show_host_key_dialog)
        redacted = self.redactor.redact(line)
        self.overview.append_log(redacted, self._classify_line(line))

    @staticmethod
    def _classify_line(line: str) -> str:
        stripped = strip_ansi(line).strip()
        if (
            re.search(r"\[\d/6\]", stripped)
            or stripped.startswith("SSH server:")
            or "Upload complete" in stripped
            or "Reading SSH credentials" in stripped
            or "Deployment complete" in stripped
            or "The saved key differs" in stripped
        ):
            return "step"
        if _ERROR_RE.search(stripped):
            return "error"
        if _WARN_RE.search(stripped):
            return "warn"
        if _SUCCESS_RE.search(stripped):
            return "success"
        return "normal"

    def _show_host_key_dialog(self) -> None:
        if self._closing or not self._busy or self.bridge is None:
            return
        raw = list(self._raw_tail)
        start = 0
        for index in range(len(raw) - 1, -1, -1):
            if raw[index].startswith("SSH server:"):
                start = index
                break
        evidence_lines = raw[start:]
        evidence_lines.extend(
            [
                "",
                "在服务器控制台核对当前指纹：",
                "sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256",
                "",
                "只有确认上方“当前 ED25519 host key”与控制台输出一致，才输入 YES。",
            ]
        )
        evidence = "\n".join(self.redactor.redact(line) for line in evidence_lines)
        dialog = dialogs.HostKeyDialog(evidence, self)
        result = dialog.exec_()
        if not self._busy or self.bridge is None:
            return
        if result == dialog.Accepted:
            if self.bridge.send_input("YES\n"):
                self.overview.append_log("已发送主机密钥确认（YES），继续。", "warn")
                self.overview.set_progress_detail("已确认替换 SSH 主机密钥，等待服务器继续…")
            else:
                self.overview.append_log("无法写入确认输入，进程可能已经结束。", "error")
        else:
            self._host_canceled = True
            self.bridge.send_input("\n")
            self.overview.append_log("已取消主机密钥更新；保留原有 known_hosts 记录。", "warn")
            self.overview.set_progress_detail("已取消主机密钥更新。")

    def _cancel_action(self) -> None:
        if not self._busy or self.bridge is None:
            return
        if not dialogs.confirm_cancel_action(self):
            return
        if not self._busy or self.bridge is None:
            return
        self.bridge.cancel()
        self.overview.append_log("正在终止本地进程…", "warn")
        self.overview.set_progress_detail("正在终止本地进程；远程部署可能被中断。")

    def _tick_elapsed(self) -> None:
        if not self._busy or self._closing:
            self._elapsed_timer.stop()
            return
        elapsed = int(time.monotonic() - self._started_at)
        self.overview.set_elapsed(elapsed)
        if (
            not self._quiet_notified
            and time.monotonic() - self._last_output_at > 20
        ):
            self._quiet_notified = True
            self.overview.set_progress_detail(
                "超过 20 秒没有新输出，可能正在下载镜像或等待服务器；"
                "若长时间无响应，可取消后重试。"
            )

    def _on_process_finished(self, outcome: ProcessOutcome) -> None:
        if self._closing or self._finishing or self._action_key is None:
            return
        self._finishing = True
        action_key = self._action_key
        meta = dict(self._action_meta)
        self._elapsed_timer.stop()
        self._busy = False
        self.overview.set_elapsed(int(outcome.duration))
        spec = commands.ACTIONS_BY_KEY.get(action_key)
        success = (
            outcome.exit_code == 0
            and not outcome.canceled
            and not self._host_canceled
        )
        duration_text = self._format_duration(outcome.duration)
        if outcome.launch_error:
            self.overview.append_log(outcome.launch_error, "error")
        self.overview.append_footer(
            f"结束 · 退出码 {outcome.exit_code} · 用时 {duration_text}", success
        )
        raw_text = "\n".join(self._current_output)
        if success:
            self._apply_action_status(action_key, meta, raw_text)
            if action_key in {"deploy", "sync_key"}:
                self._reload_after_action()

        message, dialog_kind = self._result_message(
            action_key, success, outcome, raw_text
        )
        if success:
            level = "success"
        elif outcome.canceled or self._host_canceled:
            level = "warn"
        else:
            level = "error"
        self.overview.finish_operation(success, message, level)
        self._update_actions()
        self.statusBar().showMessage(message, 8000)
        if dialog_kind == "info":
            QMessageBox.information(self, spec.title if spec else "完成", message)
        elif dialog_kind == "warning":
            QMessageBox.warning(self, spec.title if spec else "操作失败", message)
        self.bridge = None
        self._action_key = None
        self._action_meta = {}
        self._finishing = False

    def _apply_action_status(self, action_key: str, meta: dict, raw_text: str) -> None:
        report = parse_status(raw_text)
        if action_key in {"status", "start", "deploy"}:
            if action_key in {"start", "deploy"} and report.services == "unknown":
                report.services = "running"
            self._apply_report(report)
        elif action_key == "stop":
            if meta.get("dry_run"):
                return
            previous = self.status_report
            stopped = StatusReport(
                services="stopped",
                qq="unknown",
                watchdog="inactive",
                voice_enabled=previous.voice_enabled,
                voice_model=previous.voice_model,
                memory_enabled=previous.memory_enabled,
                plugins_active=previous.plugins_active,
                checked_at=datetime.now(),
            )
            self.status_report = stopped
            self.overview.mark_stopped()

    def _apply_report(self, report: StatusReport) -> None:
        self.status_report = report
        self.overview.apply_report(report)

    def _reload_after_action(self) -> None:
        try:
            stat = self.key_path.stat()
        except OSError:
            self._load_config(quiet=True)
            return
        if self.doc is None or stat.st_mtime_ns != self.doc.mtime_ns or stat.st_size != self.doc.size:
            if self.settings_page.is_dirty():
                if dialogs.ask_reload_discard(
                    self, "服务器已回填 Token，本地 key.txt 已更新；要重新载入吗？"
                ):
                    self._load_config(quiet=True)
            else:
                self._load_config(quiet=True)

    def _result_message(
        self,
        action_key: str,
        success: bool,
        outcome: ProcessOutcome,
        raw_text: str,
    ) -> tuple[str, str]:
        if outcome.canceled:
            return "操作已取消，本地进程已终止。", ""
        if self._host_canceled:
            return "已取消 SSH 主机密钥更新，操作未继续。", ""
        if success:
            if action_key == "deploy":
                qq = self.status_report.qq
                if qq == "online":
                    return "部署 / 更新完成，QQ 当前在线。", "info"
                return (
                    "部署 / 更新完成。QQ 尚未登录时，请打开 NapCat 后台扫码；"
                    "这一步必须由你本人完成。",
                    "info",
                )
            return {
                "status": "状态已刷新。",
                "start": "启动命令完成。",
                "stop": (
                    "停止预览完成，未改动服务器。"
                    if self._action_meta.get("dry_run")
                    else "服务已停止，QQ 已离线；下次启动需要快速登录或扫码。"
                ),
                "sync_key": "Token 已同步回本机 key.txt。",
                "sync_password": "密码兜底文件已同步到服务器（内容未显示）。",
            }.get(action_key, "操作完成。"), ""
        detail = self._last_error_line(raw_text)
        prefix = "操作失败" if outcome.exit_code != 0 else "操作未完成"
        if outcome.launch_error:
            message = f"{prefix}：{outcome.launch_error}"
            return message, "warning"
        message = f"{prefix}（退出码 {outcome.exit_code}）。"
        if detail:
            message += f"\n最近错误：{detail}"
        message += "\n详细输出已在运行日志中脱敏显示。"
        return message, "warning"

    def _last_error_line(self, raw_text: str) -> str:
        lines = [strip_ansi(line).strip() for line in raw_text.splitlines() if line.strip()]
        for line in reversed(lines):
            if _ERROR_RE.search(line):
                return self.redactor.redact(line)[:300]
        if lines:
            return self.redactor.redact(lines[-1])[:300]
        return ""

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = int(max(0.0, seconds))
        minutes, secs = divmod(total, 60)
        if minutes:
            return f"{minutes} 分 {secs:02d} 秒"
        return f"{secs} 秒"

    # ---------------- open helpers ----------------

    def _open_url(self, url: str) -> None:
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, "打开链接失败", f"无法打开链接：{url}")

    def _open_key_file(self) -> None:
        if not self.key_path.is_file():
            dialogs.show_error(self, "找不到 key.txt", str(self.key_path))
            return
        open_local_path(self.key_path)

    def _open_project(self) -> None:
        open_local_path(self.project_root)

    def _open_readme(self) -> None:
        readme = self.project_root / "README.md"
        if not readme.is_file():
            dialogs.show_error(self, "找不到 README.md", str(readme))
            return
        open_local_path(readme)

    def _open_terminal(self) -> None:
        if not self.script_path.is_file():
            dialogs.show_error(self, "缺少 upload.ps1", "无法打开 SSH 终端。")
            return
        if self.settings_page.is_dirty():
            if not dialogs.ask_save_before_action(self):
                return
            if not self._save_config(show_message=False):
                return
        if not self._ensure_key_current():
            return
        if not self._can_ssh():
            dialogs.show_error(self, "配置不完整", "需要先填写 SSH 凭据。")
            return
        shell = commands.powershell_executable() or "powershell.exe"
        try:
            subprocess.Popen(
                [
                    shell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-NoExit",
                    "-File",
                    str(self.script_path),
                    "-Connect",
                ],
                cwd=str(self.project_root),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as exc:
            dialogs.show_error(self, "无法打开 SSH 终端", f"{exc.strerror or exc}")
            return
        self.statusBar().showMessage(
            "已在新窗口打开 SSH 终端；主机密钥和密码提示只在该窗口显示。", 6000
        )

    # ---------------- window state ----------------

    def _restore_geometry(self) -> None:
        geometry = self.qsettings.value("geometry")
        if geometry is not None:
            try:
                self.restoreGeometry(geometry)
            except (TypeError, ValueError):
                pass
        # 旧版本可能保存过小于当前窗口最小尺寸的 geometry，恢复后要重新夹紧。
        width = max(self.width(), self.minimumWidth())
        height = max(self.height(), self.minimumHeight())
        if (width, height) != (self.width(), self.height()):
            self.resize(width, height)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._busy:
            if not dialogs.confirm_close_busy(self):
                event.ignore()
                return
            self._closing = True
            self._elapsed_timer.stop()
            if self.bridge is not None:
                self.bridge.cancel()
                self.bridge.wait(3)
        elif self.settings_page.is_dirty():
            box = QMessageBox(self)
            box.setWindowTitle("有未保存的配置")
            box.setIcon(QMessageBox.Warning)
            box.setText("配置页有未保存的修改，退出会丢弃这些修改。")
            discard = box.addButton("放弃修改并退出", QMessageBox.DestructiveRole)
            cancel = box.addButton("取消", QMessageBox.RejectRole)
            box.setDefaultButton(cancel)
            box.exec_()
            if box.clickedButton() is not discard:
                event.ignore()
                return
        self.qsettings.setValue("geometry", self.saveGeometry())
        self.qsettings.setValue("page", self.stack.currentIndex())
        self.qsettings.setValue("theme", self._theme_name)
        event.accept()
