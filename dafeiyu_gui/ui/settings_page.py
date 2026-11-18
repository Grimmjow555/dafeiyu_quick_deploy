"""配置页：编辑 key.txt 中已有字段，不新增或猜测字段。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from dafeiyu_gui.backend.keyfile import (
    FIELD_GROUPS,
    FIELD_SPECS,
    KeyDocument,
    ValidationIssue,
    missing_required,
)
from dafeiyu_gui.ui.widgets import Banner, PasswordLineEdit, SectionCard


class SettingsPage(QWidget):
    save_requested = pyqtSignal()
    reload_requested = pyqtSignal()
    open_key_file_requested = pyqtSignal()
    open_project_requested = pyqtSignal()
    sync_password_requested = pyqtSignal()
    dirty_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc: KeyDocument | None = None
        self._editors: dict[str, QLineEdit] = {}
        self._password_widgets: list[PasswordLineEdit] = []
        self._error_labels: dict[str, QLabel] = {}
        self._loading = False
        self._dirty = False
        self._busy = False
        self._external_save_enabled = False
        self._qq_present = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("配置 key.txt")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        description = QLabel(
            "字段与部署脚本读取的 key.txt 完全一致；保存时保留注释、顺序、末尾 URL 行和未知字段。"
            "敏感值默认隐藏，不会写入日志。"
        )
        description.setObjectName("PageDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.banner = Banner()
        layout.addWidget(self.banner)

        top_row = QHBoxLayout()
        self.reveal_check = QCheckBox("显示敏感字段")
        self.reveal_check.toggled.connect(self._set_reveal)
        top_row.addWidget(self.reveal_check)
        top_row.addStretch(1)
        self.dirty_label = QLabel("")
        self.dirty_label.setObjectName("FieldError")
        top_row.addWidget(self.dirty_label)
        layout.addLayout(top_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 6, 0)
        content_layout.setSpacing(12)
        for group in FIELD_GROUPS:
            specs = [spec for spec in FIELD_SPECS if spec.group == group]
            card = SectionCard(group)
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
            form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(10)
            for spec in specs:
                self._add_field(form, spec)
            card.body.addLayout(form)
            content_layout.addWidget(card)
        self._add_qq_card(content_layout)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.open_key_button = QPushButton("打开 key.txt")
        self.open_key_button.setObjectName("LinkButton")
        self.open_key_button.clicked.connect(self.open_key_file_requested)
        self.open_project_button = QPushButton("打开项目目录")
        self.open_project_button.setObjectName("LinkButton")
        self.open_project_button.clicked.connect(self.open_project_requested)
        footer.addWidget(self.open_key_button)
        footer.addWidget(self.open_project_button)
        footer.addStretch(1)
        self.footer_hint = QLabel("保存后需要重新运行「一键部署 / 更新」才会应用。")
        self.footer_hint.setObjectName("FooterHint")
        footer.addWidget(self.footer_hint)
        self.reload_button = QPushButton("重新载入")
        self.reload_button.clicked.connect(self.reload_requested)
        footer.addWidget(self.reload_button)
        self.save_button = QPushButton("保存 key.txt")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self.save_requested)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)
        self._apply_editable_state()

    def _add_field(self, form: QFormLayout, spec) -> None:
        label = QLabel(spec.label)
        label.setMinimumWidth(130)
        editor_box = QWidget()
        editor_layout = QVBoxLayout(editor_box)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(2)
        if spec.secret:
            editor = PasswordLineEdit()
            editor.setPlaceholderText(spec.placeholder or "已填写时显示为圆点")
            self._password_widgets.append(editor)
            line_edit = editor.line_edit
        else:
            editor = QLineEdit()
            editor.setPlaceholderText(spec.placeholder)
            line_edit = editor
            editor_layout.addWidget(editor)
        if spec.secret:
            editor_layout.addWidget(editor)
        if spec.hint:
            hint = QLabel(spec.hint)
            hint.setObjectName("FieldHint")
            hint.setWordWrap(True)
            editor_layout.addWidget(hint)
        error = QLabel("")
        error.setObjectName("FieldError")
        error.setWordWrap(True)
        error.hide()
        editor_layout.addWidget(error)
        line_edit.textChanged.connect(lambda _text, field=spec.name: self._on_edited(field))
        self._editors[spec.name] = line_edit
        self._error_labels[spec.name] = error
        form.addRow(label, editor_box)

    def _add_qq_card(self, content_layout: QVBoxLayout) -> None:
        card = SectionCard(
            "QQ 密码兜底（可选）",
            "界面从不读取或显示 QQ.txt 内容。存在该文件时部署成功会自动同步为服务器 "
            "~/dafeiyu/secret/qq-login.txt（600）。",
        )
        row = QHBoxLayout()
        self.qq_status_label = QLabel("未检测到 QQ.txt")
        self.qq_status_label.setObjectName("CardHint")
        self.qq_status_label.setWordWrap(True)
        row.addWidget(self.qq_status_label, 1)
        self.sync_password_button = QPushButton("同步到服务器")
        self.sync_password_button.clicked.connect(self.sync_password_requested)
        row.addWidget(self.sync_password_button)
        card.body.addLayout(row)
        hint = QLabel(
            "只想在服务器本地开启：用 SSH 终端执行 sudo python3 qq_watchdog.py --set-password。"
            "密码错误会暂停 24 小时；修改后不需要重启守护进程。"
        )
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        content_layout.addWidget(card)

    def _on_edited(self, field: str = "") -> None:
        if self._loading:
            return
        if field and field in self._error_labels:
            self._error_labels[field].clear()
            self._error_labels[field].hide()
        if not self._dirty:
            self._dirty = True
            self.dirty_label.setText("● 有未保存修改")
            self.dirty_changed.emit(True)

    def _set_reveal(self, revealed: bool) -> None:
        for editor in self._password_widgets:
            editor.set_revealed(revealed)

    def _apply_editable_state(self) -> None:
        parse_broken = bool(self._doc and self._doc.parse_errors)
        has_doc = self._doc is not None and not parse_broken
        editable = not self._busy and has_doc
        for editor in self._editors.values():
            editor.setEnabled(editable)
        self.save_button.setEnabled(
            editable and self._external_save_enabled and self._doc is not None
        )
        self.reload_button.setEnabled(not self._busy)
        self.open_key_button.setEnabled(True)
        self.open_project_button.setEnabled(True)

    def load_document(self, doc: KeyDocument | None) -> None:
        self._loading = True
        try:
            self._doc = doc
            values = doc.values if doc else {}
            for name, editor in self._editors.items():
                editor.setText(values.get(name, ""))
            for label in self._error_labels.values():
                label.clear()
                label.hide()
            self._dirty = False
            self.dirty_label.setText("")
            self.dirty_changed.emit(False)
            self.reveal_check.setChecked(False)
            if doc is None:
                self.banner.show_message("未找到或无法读取 key.txt，请先修正文件。", "error")
            elif doc.parse_errors:
                self.banner.show_message(
                    "key.txt 存在格式问题，保存已禁用：" + "；".join(doc.parse_errors[:3]), "error"
                )
            else:
                self.banner.hide_banner()
        finally:
            self._loading = False
        self._apply_editable_state()

    def values(self) -> dict[str, str]:
        return {name: editor.text().strip() for name, editor in self._editors.items()}

    def is_dirty(self) -> bool:
        return self._dirty

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._apply_editable_state()

    def set_save_enabled(self, enabled: bool) -> None:
        self._external_save_enabled = enabled
        self._apply_editable_state()

    def set_validation_issues(self, issues: list[ValidationIssue]) -> None:
        for label in self._error_labels.values():
            label.clear()
            label.hide()
        for issue in issues:
            label = self._error_labels.get(issue.field)
            if label is not None:
                label.setText(issue.message)
                label.show()
        if not self._doc or self._doc.parse_errors:
            return
        if issues:
            level = "error" if any(issue.is_error for issue in issues) else "warn"
            summary = "；".join(issue.message for issue in issues[:4])
            if len(issues) > 4:
                summary += f"；等 {len(issues)} 项"
            self.banner.show_message(summary, level)
        elif missing_required(self.values()):
            names = "、".join(missing_required(self.values()))
            self.banner.show_message(f"配置不完整，部署前需要填写：{names}", "warn")
        else:
            self.banner.hide_banner()

    def mark_saved_message(self, text: str) -> None:
        self.banner.show_message(text, "success")

    def set_qq_password_present(self, present: bool, path: Path | None = None) -> None:
        self._qq_present = present
        if present:
            location = f"（{path.name}）" if path else ""
            self.qq_status_label.setText(f"已检测到 QQ.txt{location}；内容不会被读取或显示。")
        else:
            self.qq_status_label.setText(
                "未检测到 QQ.txt。需要密码兜底时，按 README 第 4 节在项目目录创建该文件。"
            )
        self.sync_password_button.setEnabled(present and not self._busy)
        self.sync_password_button.setToolTip(
            "执行 upload.ps1 -SyncPassword；内容不会显示。" if present else "项目目录没有 QQ.txt"
        )

    def set_sync_password_enabled(self, enabled: bool) -> None:
        self.sync_password_button.setEnabled(enabled and self._qq_present and not self._busy)

    def focus_field(self, name: str) -> None:
        editor = self._editors.get(name)
        if editor is not None:
            editor.setFocus()
            editor.selectAll()

    def discard_unsaved(self) -> None:
        """把表单恢复到最近一次加载的文档内容。"""
        self.load_document(self._doc)
