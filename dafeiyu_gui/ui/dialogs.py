"""确认、停止选项和 SSH 主机密钥对话框。"""

from __future__ import annotations

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def confirm_deploy(parent: QWidget, host: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("开始部署 / 更新")
    box.setIcon(QMessageBox.Question)
    box.setText(f"即将连接 {host} 并上传部署包。")
    box.setInformativeText(
        "首次部署可能需要十几分钟（下载镜像和插件较慢）。\n"
        "重复运行是幂等的，已有数据和 QQ 会话会保留。\n"
        "部署结束后 QQ 仍需你在 NapCat 后台扫码登录。"
    )
    start_button = box.addButton("开始部署", QMessageBox.AcceptRole)
    cancel_button = box.addButton("取消", QMessageBox.RejectRole)
    box.setDefaultButton(cancel_button)
    box.exec_()
    return box.clickedButton() is start_button


class StopOptionsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("停止服务")
        self.setModal(True)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        warning = QLabel("停止后 QQ 会离线，下次启动可能需要快速登录或重新扫码。data/、napcat/ 不会删除。")
        warning.setObjectName("CardHint")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.real_radio = QRadioButton("停止服务（先停掉掉线守护，再停 NapCat、AstrBot）")
        self.real_radio.setChecked(True)
        self.dry_run_radio = QRadioButton("仅预览（--dry-run），不做任何改动")
        layout.addWidget(self.real_radio)
        layout.addWidget(self.dry_run_radio)
        form = QFormLayout()
        form.setSpacing(8)
        self.down_check = QCheckBox("停止后移除容器（--down，不删除数据）")
        self.timeout_check = QCheckBox("自定义优雅退出等待时间")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 3600)
        self.timeout_spin.setValue(60)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setEnabled(False)
        self.timeout_check.toggled.connect(self.timeout_spin.setEnabled)
        form.addRow("", self.down_check)
        timeout_row = QWidget()
        from PyQt5.QtWidgets import QHBoxLayout

        timeout_layout = QHBoxLayout(timeout_row)
        timeout_layout.setContentsMargins(0, 0, 0, 0)
        timeout_layout.setSpacing(8)
        timeout_layout.addWidget(self.timeout_check)
        timeout_layout.addWidget(self.timeout_spin)
        timeout_layout.addStretch(1)
        form.addRow("", timeout_row)
        layout.addLayout(form)
        self.dry_run_radio.toggled.connect(self._update_options)
        buttons = QDialogButtonBox()
        self.ok_button = buttons.addButton("执行", QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        self.ok_button.setObjectName("DangerButton")
        self.ok_button.setText("仅预览" if self.dry_run_radio.isChecked() else "停止服务")
        cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_options(self) -> None:
        dry_run = self.dry_run_radio.isChecked()
        self.down_check.setEnabled(not dry_run)
        self.timeout_check.setEnabled(not dry_run)
        self.timeout_spin.setEnabled(not dry_run and self.timeout_check.isChecked())
        self.ok_button.setText("仅预览" if dry_run else "停止服务")
        self.ok_button.setObjectName("PrimaryButton" if dry_run else "DangerButton")
        style = self.ok_button.style()
        style.unpolish(self.ok_button)
        style.polish(self.ok_button)
        self.ok_button.update()

    def options(self) -> tuple[bool, bool, int | None]:
        dry_run = self.dry_run_radio.isChecked()
        down = self.down_check.isChecked() and not dry_run
        timeout = self.timeout_spin.value() if self.timeout_check.isChecked() and not dry_run else None
        return dry_run, down, timeout


class HostKeyDialog(QDialog):
    """SSH 主机密钥变化确认。

    upload.ps1 的 Read-Host 提示不会出现在管道输出中，因此由 GUI 在捕获到
    "The saved key differs." 后弹出此对话框。用户必须输入 YES 才能继续。
    """

    def __init__(self, evidence: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SSH 主机密钥发生变化")
        self.setModal(True)
        self.setMinimumSize(700, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel("服务器返回的主机密钥与本机 known_hosts 中保存的不一致")
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        explain = QLabel(
            "可能是服务器重装了系统，也可能是中间人攻击。请先到阿里云控制台的远程终端核对指纹：\n"
            "sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256\n"
            "确认下方“当前”指纹与控制台输出一致后，输入 YES 继续；否则请取消。"
        )
        explain.setObjectName("CardHint")
        explain.setWordWrap(True)
        layout.addWidget(explain)
        evidence_view = QPlainTextEdit()
        evidence_view.setReadOnly(True)
        evidence_view.setPlainText(evidence)
        evidence_view.setFont(QFont("Consolas", 9))
        layout.addWidget(evidence_view, 1)
        form = QFormLayout()
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setPlaceholderText("输入 YES 以替换并继续")
        self.confirm_edit.textChanged.connect(self._update_ok)
        form.addRow("确认", self.confirm_edit)
        layout.addLayout(form)
        hint = QLabel("不会自动确认；取消（或直接关闭窗口）会保留原来的主机记录。")
        hint.setObjectName("CardHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        from PyQt5.QtWidgets import QDialogButtonBox

        buttons = QDialogButtonBox()
        self.ok_button = buttons.addButton("替换并继续", QDialogButtonBox.AcceptRole)
        self.ok_button.setObjectName("DangerButton")
        self.ok_button.setEnabled(False)
        cancel = buttons.addButton("取消（保留原记录）", QDialogButtonBox.RejectRole)
        cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_ok(self, text: str) -> None:
        self.ok_button.setEnabled(text.strip() == "YES")


def ask_save_before_action(parent: QWidget) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("配置有未保存的修改")
    box.setIcon(QMessageBox.Warning)
    box.setText("运行操作前需要先保存 key.txt。")
    box.setInformativeText("当前表单里的修改还没有写入磁盘，upload.ps1 会读取磁盘上的旧配置。")
    save = box.addButton("保存并继续", QMessageBox.AcceptRole)
    cancel = box.addButton("取消", QMessageBox.RejectRole)
    box.setDefaultButton(save)
    box.exec_()
    return box.clickedButton() is save


def ask_reload_discard(parent: QWidget, message: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("key.txt 已被外部修改")
    box.setIcon(QMessageBox.Warning)
    box.setText(message)
    box.setInformativeText("重新载入会丢弃当前表单里未保存的修改。")
    reload_button = box.addButton("重新载入", QMessageBox.AcceptRole)
    cancel = box.addButton("取消", QMessageBox.RejectRole)
    box.setDefaultButton(cancel)
    box.exec_()
    return box.clickedButton() is reload_button


def confirm_cancel_action(parent: QWidget) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("取消当前操作")
    box.setIcon(QMessageBox.Warning)
    box.setText("确定终止本地操作吗？")
    box.setInformativeText(
        "这会结束本地 PowerShell/SSH 进程。服务器上的部署可能被中断，也可能继续执行；"
        "之后可以安全地重跑一键部署（幂等）。"
    )
    yes = box.addButton("终止操作", QMessageBox.DestructiveRole)
    no = box.addButton("继续等待", QMessageBox.RejectRole)
    box.setDefaultButton(no)
    box.exec_()
    return box.clickedButton() is yes


def confirm_close_busy(parent: QWidget) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("操作仍在运行")
    box.setIcon(QMessageBox.Warning)
    box.setText("当前操作仍在运行，关闭窗口会终止本地进程。")
    box.setInformativeText("服务器上的部署可能被中断；重新打开后可以再运行一次一键部署。")
    yes = box.addButton("关闭并终止", QMessageBox.DestructiveRole)
    no = box.addButton("继续等待", QMessageBox.RejectRole)
    box.setDefaultButton(no)
    box.exec_()
    return box.clickedButton() is yes


def show_error(parent: QWidget, title: str, message: str, details: str = "") -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Critical)
    box.setText(message)
    if details:
        box.setDetailedText(details)
    box.exec_()
