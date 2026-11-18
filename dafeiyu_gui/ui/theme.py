"""浅色 / 深色主题与 QSS。"""

from __future__ import annotations

from string import Template

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

LIGHT: dict[str, str] = {
    "bg": "#F3F6FB",
    "surface": "#FFFFFF",
    "surface_alt": "#F7F9FD",
    "surface_soft": "#EAF1FE",
    "border": "#DFE6F1",
    "text": "#1F2937",
    "muted": "#667085",
    "primary": "#2F6FED",
    "primary_hover": "#245CCB",
    "primary_soft": "#E8F0FE",
    "success": "#16875A",
    "success_soft": "#E7F6EF",
    "warning": "#B26A00",
    "warning_soft": "#FFF3DE",
    "danger": "#C93B3B",
    "danger_soft": "#FDECEC",
    "info": "#2F6FED",
    "info_soft": "#E8F0FE",
    "disabled": "#A5AEBE",
    "log_bg": "#0F1729",
    "log_text": "#D8E3F3",
}

DARK: dict[str, str] = {
    "bg": "#0F1522",
    "surface": "#172033",
    "surface_alt": "#1C2740",
    "surface_soft": "#223255",
    "border": "#2A3852",
    "text": "#E8EEF9",
    "muted": "#94A3B8",
    "primary": "#6C9BFF",
    "primary_hover": "#86ADFF",
    "primary_soft": "#1E2F55",
    "success": "#4FD1A1",
    "success_soft": "#183B32",
    "warning": "#F2C14E",
    "warning_soft": "#3A2F1A",
    "danger": "#FF7A7A",
    "danger_soft": "#3A1F25",
    "info": "#6C9BFF",
    "info_soft": "#1E2F55",
    "disabled": "#5A6A85",
    "log_bg": "#0A101C",
    "log_text": "#D8E3F3",
}

THEMES = {"light": LIGHT, "dark": DARK}

_QSS = Template(
    """
    QWidget {
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
        font-size: 9.5pt;
        color: $text;
    }
    QMainWindow, QDialog, QMessageBox, QWidget#Root {
        background-color: $bg;
    }
    QStackedWidget#Pages {
        background: transparent;
    }
    QScrollArea {
        background: transparent;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background: transparent;
    }
    QFrame#Sidebar {
        background-color: $surface;
        border-right: 1px solid $border;
    }
    QFrame#Header {
        background: transparent;
        border-bottom: 1px solid $border;
    }
    QLabel#AppTitle {
        font-size: 14pt;
        font-weight: 700;
    }
    QLabel#AppSubtitle, QLabel#CardHint, QLabel#CardDetail, QLabel#Subtle,
    QLabel#FieldHint, QLabel#FooterHint, QLabel#PageDescription {
        color: $muted;
    }
    QLabel#AppSubtitle {
        font-size: 8.5pt;
    }
    QLabel#PageTitle {
        font-size: 15pt;
        font-weight: 700;
    }
    QLabel#PageDescription {
        font-size: 9pt;
    }
    QLabel#CardTitle {
        font-size: 11pt;
        font-weight: 600;
    }
    QLabel#CardHint {
        font-size: 9pt;
    }
    QLabel#CardDetail {
        font-size: 8.5pt;
    }
    QLabel#StatusValue {
        font-size: 12pt;
        font-weight: 600;
    }
    QLabel#StatusDot {
        font-size: 12pt;
        color: $muted;
    }
    QLabel#StatusDot[state="ok"] { color: $success; }
    QLabel#StatusDot[state="warn"] { color: $warning; }
    QLabel#StatusDot[state="bad"] { color: $danger; }
    QLabel#StatusDot[state="info"] { color: $primary; }
    QLabel#ServerChip {
        background-color: $surface_soft;
        color: $primary;
        border: 1px solid $border;
        border-radius: 12px;
        padding: 4px 12px;
        font-size: 8.5pt;
    }
    QLabel#InlineNote {
        color: $muted;
        font-size: 8.5pt;
    }
    QLabel#FieldError {
        color: $danger;
        font-size: 8.5pt;
    }
    QLabel#FieldHint {
        font-size: 8.5pt;
    }
    QLabel#StepChip {
        border-radius: 10px;
        padding: 3px 9px;
        background-color: $surface_alt;
        color: $muted;
        font-size: 8.5pt;
        border: 1px solid transparent;
    }
    QLabel#StepChip[stepState="done"] {
        background-color: $success_soft;
        color: $success;
    }
    QLabel#StepChip[stepState="current"] {
        background-color: $primary;
        color: #FFFFFF;
        font-weight: 600;
    }
    QLabel#StepArrow {
        color: $muted;
        font-size: 9pt;
    }
    QFrame#Card {
        background-color: $surface;
        border: 1px solid $border;
        border-radius: 12px;
    }
    QFrame#ProgressPanel {
        background-color: $surface;
        border: 1px solid $border;
        border-radius: 12px;
    }
    QFrame#Banner {
        border: 1px solid $border;
        border-radius: 8px;
        background-color: $surface_alt;
    }
    QFrame#Banner[level="warn"] {
        background-color: $warning_soft;
        border-color: $warning;
    }
    QFrame#Banner[level="error"] {
        background-color: $danger_soft;
        border-color: $danger;
    }
    QFrame#Banner[level="success"] {
        background-color: $success_soft;
        border-color: $success;
    }
    QFrame#Banner[level="info"] {
        background-color: $info_soft;
        border-color: $info;
    }
    QFrame#Banner QLabel {
        background: transparent;
        color: $text;
    }
    QPushButton {
        background-color: $surface_alt;
        color: $text;
        border: 1px solid $border;
        border-radius: 8px;
        padding: 7px 14px;
        min-height: 20px;
    }
    QPushButton:hover {
        border-color: $primary;
    }
    QPushButton:pressed {
        background-color: $border;
    }
    QPushButton:disabled {
        color: $disabled;
        background-color: $surface_alt;
        border-color: $border;
    }
    QPushButton#PrimaryButton {
        background-color: $primary;
        color: #FFFFFF;
        border: 1px solid $primary;
        font-weight: 600;
        padding: 9px 18px;
    }
    QPushButton#PrimaryButton:hover {
        background-color: $primary_hover;
        border-color: $primary_hover;
    }
    QPushButton#PrimaryButton:disabled {
        background-color: $surface_soft;
        color: $disabled;
        border-color: $border;
    }
    QPushButton#DangerButton {
        background: transparent;
        color: $danger;
        border-color: $danger;
    }
    QPushButton#DangerButton:hover {
        background-color: $danger_soft;
    }
    QPushButton#LinkButton {
        background: transparent;
        border: none;
        color: $primary;
        padding: 4px 6px;
        text-align: left;
    }
    QPushButton#LinkButton:hover {
        text-decoration: underline;
    }
    QPushButton#NavButton {
        background: transparent;
        border: 1px solid transparent;
        border-left: 3px solid transparent;
        border-radius: 8px;
        color: $muted;
        padding: 10px 12px;
        text-align: left;
        font-size: 10pt;
    }
    QPushButton#NavButton:hover {
        background-color: $surface_alt;
        color: $text;
    }
    QPushButton#NavButton:checked {
        background-color: $primary_soft;
        border-left: 3px solid $primary;
        color: $primary;
        font-weight: 600;
    }
    QToolButton#EyeButton {
        background: $surface_alt;
        color: $muted;
        border: 1px solid $border;
        border-radius: 7px;
        padding: 4px 8px;
        min-width: 38px;
    }
    QToolButton#EyeButton:hover {
        color: $primary;
        border-color: $primary;
    }
    QLineEdit, QSpinBox, QComboBox {
        background-color: $surface_alt;
        color: $text;
        border: 1px solid $border;
        border-radius: 8px;
        padding: 7px 10px;
        selection-background-color: $primary;
        selection-color: #FFFFFF;
    }
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
        border-color: $primary;
        background-color: $surface;
    }
    QLineEdit:disabled, QSpinBox:disabled {
        color: $disabled;
    }
    QPlainTextEdit#LogView {
        background-color: $log_bg;
        border: 1px solid $border;
        border-radius: 10px;
        color: $log_text;
        font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
        font-size: 9pt;
        selection-background-color: $primary;
        selection-color: #FFFFFF;
        padding: 6px;
    }
    QCheckBox {
        color: $text;
        spacing: 6px;
    }
    QCheckBox::indicator {
        width: 15px;
        height: 15px;
    }
    QRadioButton {
        color: $text;
        spacing: 6px;
    }
    QProgressBar {
        background-color: $surface_alt;
        border: 1px solid $border;
        border-radius: 5px;
        height: 8px;
        text-align: center;
        color: transparent;
    }
    QProgressBar::chunk {
        background-color: $primary;
        border-radius: 4px;
    }
    QScrollBar:vertical {
        background: transparent;
        width: 10px;
        margin: 2px;
    }
    QScrollBar::handle:vertical {
        background: $border;
        border-radius: 4px;
        min-height: 28px;
    }
    QScrollBar::handle:vertical:hover {
        background: $muted;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 10px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal {
        background: $border;
        border-radius: 4px;
        min-width: 28px;
    }
    QStatusBar {
        background-color: $surface;
        border-top: 1px solid $border;
        color: $muted;
        font-size: 8.5pt;
    }
    QTextBrowser#HelpView {
        background-color: $surface;
        border: 1px solid $border;
        border-radius: 10px;
        padding: 10px;
        color: $text;
    }
    QToolTip {
        background-color: $surface;
        color: $text;
        border: 1px solid $border;
        padding: 4px;
    }
    QMessageBox QLabel {
        color: $text;
    }
    """
)


def apply_theme(app: QApplication, name: str) -> dict[str, str]:
    colors = THEMES.get(name, LIGHT)
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(colors["bg"]))
    palette.setColor(QPalette.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.Base, QColor(colors["surface"]))
    palette.setColor(QPalette.AlternateBase, QColor(colors["surface_alt"]))
    palette.setColor(QPalette.Text, QColor(colors["text"]))
    palette.setColor(QPalette.Button, QColor(colors["surface"]))
    palette.setColor(QPalette.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.Highlight, QColor(colors["primary"]))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ToolTipBase, QColor(colors["surface"]))
    palette.setColor(QPalette.ToolTipText, QColor(colors["text"]))
    app.setPalette(palette)
    app.setStyleSheet(_QSS.substitute(colors))
    return colors
