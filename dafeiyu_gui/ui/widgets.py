"""可复用的小组件：卡片、状态、阶段条、日志、密码输入行。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dafeiyu_gui.backend.status import StatusReport
from dafeiyu_gui.backend.steps import STEP_LABELS

LOG_COLORS = {
    "normal": "#D8E3F3",
    "muted": "#8193AD",
    "step": "#7FB0FF",
    "error": "#FF8585",
    "warn": "#F2C14E",
    "success": "#5DD39E",
}


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class SectionCard(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        header = QVBoxLayout()
        header.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        header.addWidget(self.title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("CardHint")
            subtitle_label.setWordWrap(True)
            header.addWidget(subtitle_label)
        layout.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        layout.addLayout(self.body)


class StatusCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedHeight(84)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 8)
        layout.setSpacing(1)
        self._title = QLabel(title)
        self._title.setObjectName("CardHint")
        layout.addWidget(self._title)
        value_row = QHBoxLayout()
        value_row.setSpacing(7)
        self._dot = QLabel("●")
        self._dot.setObjectName("StatusDot")
        self._dot.setProperty("state", "idle")
        self._value = QLabel("未知")
        self._value.setObjectName("StatusValue")
        value_row.addWidget(self._dot)
        value_row.addWidget(self._value, 1)
        layout.addLayout(value_row)
        self._detail = QLabel("")
        self._detail.setObjectName("CardDetail")
        self._detail.setWordWrap(False)
        self._detail.setFixedHeight(16)
        layout.addWidget(self._detail)

    def set_state(self, value: str, state: str = "idle", detail: str = "") -> None:
        self._value.setText(value)
        self._detail.setText(detail)
        self._detail.setToolTip(detail)
        self._dot.setProperty("state", state)
        repolish(self._dot)


def _state_for_service(services: str) -> str:
    return {"running": "ok", "stopped": "warn"}.get(services, "idle")


def _state_for_qq(qq: str) -> str:
    return {"online": "ok", "needs_qr": "warn", "offline": "warn"}.get(qq, "idle")


def _state_for_watchdog(watchdog: str) -> str:
    return {
        "active": "ok",
        "inactive": "warn",
        "failed": "bad",
        "not_installed": "idle",
    }.get(watchdog, "idle")


class StatusBoard(QWidget):
    """六个状态卡片。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PyQt5.QtWidgets import QGridLayout

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.services = StatusCard("服务")
        self.qq = StatusCard("QQ")
        self.watchdog = StatusCard("掉线守护")
        self.voice = StatusCard("语音")
        self.memory = StatusCard("记忆")
        self.plugins = StatusCard("插件")
        cards = [self.services, self.qq, self.watchdog, self.voice, self.memory, self.plugins]
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 3, index % 3)
        self.reset_local()

    def reset_local(self) -> None:
        self.services.set_state("未知", "idle", "尚未检查")
        self.qq.set_state("未知", "idle", "尚未检查")
        self.watchdog.set_state("未知", "idle", "尚未检查")
        self.voice.set_state("未知", "idle", "")
        self.memory.set_state("未知", "idle", "")
        self.plugins.set_state("未知", "idle", "")

    def apply_local_config(self, values: dict[str, str]) -> None:
        from dafeiyu_gui.backend.keyfile import memory_configured, voice_configured

        if voice_configured(values):
            mode = "Seed-TTS 2.0" if values.get("DOUBAO_API_KEY") else "Seed Audio 1.0"
            self.voice.set_state("已配置", "info", f"{mode}，部署时验证")
        else:
            self.voice.set_state("未配置", "idle", "将跳过语音")
        if memory_configured(values):
            self.memory.set_state("已配置", "info", "部署时验证")
        else:
            self.memory.set_state("未配置", "idle", "将跳过记忆")

    def apply_report(self, report: StatusReport) -> None:
        self.services.set_state(report.services_label, _state_for_service(report.services), "")
        qq_detail = report.qq_detail or (
            "需要在 NapCat 扫码" if report.qq == "needs_qr" else ""
        )
        if report.napcat_auth_limited:
            suffix = "NapCat 接口限流，稍后重试"
            qq_detail = f"{qq_detail}；{suffix}" if qq_detail else suffix
        self.qq.set_state(report.qq_label, _state_for_qq(report.qq), qq_detail)
        watchdog_detail = ""
        if report.watchdog == "not_installed":
            watchdog_detail = "安装部署脚本后会启用"
        self.watchdog.set_state(
            report.watchdog_label, _state_for_watchdog(report.watchdog), watchdog_detail
        )
        if report.voice_enabled is True:
            model = f"（{report.voice_model}）" if report.voice_model else ""
            self.voice.set_state("已启用", "ok", model)
        elif report.voice_enabled is False:
            self.voice.set_state("未启用", "warn", "语音测试未通过或未配置")
        if report.memory_enabled is True:
            self.memory.set_state("已启用", "ok", "bge-m3 云端记忆")
        elif report.memory_enabled is False:
            self.memory.set_state("未启用", "idle", "未配置 SiliconFlow")
        if report.plugins_active is not None:
            self.plugins.set_state(str(report.plugins_active), "ok", "已激活的插件数量")

    def mark_stopped(self) -> None:
        self.services.set_state("已停止", "warn", "容器已停止")
        self.qq.set_state("未知", "idle", "服务已停止")
        self.watchdog.set_state("未运行", "warn", "随停止命令一起停止")
        self.plugins.set_state("—", "idle", "")

    def mark_started(self) -> None:
        self.services.set_state("运行中", "ok", "启动命令已执行")
        self.watchdog.set_state("运行中", "ok", "启动命令已执行")


class StepIndicator(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._chips: list[QLabel] = []
        for index, label in enumerate(STEP_LABELS):
            if index:
                arrow = QLabel("›")
                arrow.setObjectName("StepArrow")
                layout.addWidget(arrow)
            chip = QLabel(label)
            chip.setObjectName("StepChip")
            chip.setProperty("stepState", "pending")
            self._chips.append(chip)
            layout.addWidget(chip)
        layout.addStretch(1)
        self.set_current(0)

    def set_current(self, index: int, done: bool = False) -> None:
        for position, chip in enumerate(self._chips):
            if done or position < index:
                state = "done"
            elif position == index:
                state = "current"
            else:
                state = "pending"
            chip.setProperty("stepState", state)
            repolish(chip)

    def reset(self) -> None:
        self.set_current(0)


class Banner(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setProperty("level", "info")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        self._icon = QLabel("i")
        self._icon.setFixedWidth(16)
        self._text = QLabel("")
        self._text.setWordWrap(True)
        layout.addWidget(self._icon)
        layout.addWidget(self._text, 1)
        self.hide()

    def show_message(self, text: str, level: str = "info") -> None:
        self._icon.setText({"warn": "!", "error": "!", "success": "✓", "info": "i"}.get(level, "i"))
        self._text.setText(text)
        self.setProperty("level", level)
        repolish(self)
        self.show()

    def hide_banner(self) -> None:
        self._text.clear()
        self.hide()


class LogView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(4)
        title = QLabel("运行日志")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        self._auto_scroll = QCheckBox("自动滚动")
        self._auto_scroll.setChecked(True)
        header.addSpacing(8)
        header.addWidget(self._auto_scroll)
        header.addStretch(1)
        self._clear_button = QPushButton("清空")
        self._clear_button.setObjectName("LinkButton")
        self._copy_button = QPushButton("复制")
        self._copy_button.setObjectName("LinkButton")
        self._save_button = QPushButton("保存…")
        self._save_button.setObjectName("LinkButton")
        for button in (self._clear_button, self._copy_button, self._save_button):
            header.addWidget(button)
        layout.addLayout(header)
        self.edit = QPlainTextEdit()
        self.edit.setObjectName("LogView")
        self.edit.setReadOnly(True)
        self.edit.setUndoRedoEnabled(False)
        self.edit.setMaximumBlockCount(20000)
        self.edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.edit.setFont(QFont("Consolas", 9))
        self.edit.setPlaceholderText(
            "尚未运行操作。首次使用请先在「配置」检查 key.txt，然后点击「一键部署 / 更新」。"
        )
        layout.addWidget(self.edit, 1)
        self._clear_button.clicked.connect(self.clear)
        self._copy_button.clicked.connect(self.copy_all)
        self._save_button.clicked.connect(self.save_to_file)

    def append_line(self, text: str = "", kind: str = "normal") -> None:
        cursor = QTextCursor(self.edit.document())
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(LOG_COLORS.get(kind, LOG_COLORS["normal"])))
        if kind in {"step", "error"}:
            fmt.setFontWeight(QFont.Bold)
        cursor.insertText(text + "\n", fmt)
        if self._auto_scroll.isChecked():
            bar = self.edit.verticalScrollBar()
            bar.setValue(bar.maximum())

    def append_separator(self, title: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.append_line(f"──── {stamp}  {title}  ────", "muted")

    def append_footer(self, text: str, success: bool) -> None:
        self.append_line(f"──── {text} ────", "success" if success else "error")

    def clear(self) -> None:
        self.edit.clear()

    def text(self) -> str:
        return self.edit.toPlainText()

    def copy_all(self) -> None:
        text = self.text()
        if not text:
            return
        QApplication.clipboard().setText(text)

    def save_to_file(self) -> None:
        text = self.text()
        if not text:
            QMessageBox.information(self, "保存日志", "当前没有日志可保存。")
            return
        default = str(Path.home() / f"dafeiyu-log-{datetime.now():%Y%m%d-%H%M%S}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "保存脱敏日志", default, "文本文件 (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "保存日志", f"无法写入文件：{exc.strerror or exc}")
            return
        QMessageBox.information(self, "保存日志", "日志已保存（已脱敏）。")


class PasswordLineEdit(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.line_edit = QLineEdit()
        self.line_edit.setEchoMode(QLineEdit.Password)
        self.line_edit.setInputMethodHints(
            Qt.ImhHiddenText | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
        )
        self._toggle = QToolButton()
        self._toggle.setObjectName("EyeButton")
        self._toggle.setText("显示")
        self._toggle.setCheckable(True)
        self._toggle.setCursor(Qt.PointingHandCursor)
        self._toggle.toggled.connect(self._set_revealed)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self._toggle)

    def _set_revealed(self, revealed: bool) -> None:
        self.line_edit.setEchoMode(QLineEdit.Normal if revealed else QLineEdit.Password)
        self._toggle.setText("隐藏" if revealed else "显示")

    def set_revealed(self, revealed: bool) -> None:
        self._toggle.setChecked(revealed)

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, text: str) -> None:
        self.line_edit.setText(text)

    def setPlaceholderText(self, text: str) -> None:
        self.line_edit.setPlaceholderText(text)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt 命名
        super().setEnabled(enabled)


def open_local_path(path: Path) -> bool:
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
