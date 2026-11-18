"""QApplication 入口。"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import tempfile
import traceback
from pathlib import Path

from PyQt5.QtCore import QLockFile, QSettings, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QMessageBox

from dafeiyu_gui import APP_NAME
from dafeiyu_gui.ui import theme
from dafeiyu_gui.ui.main_window import MainWindow

_APP_DIR = Path(__file__).resolve().parent


def _candidate_project_roots() -> list[Path]:
    """返回可能包含 upload.ps1 / key.txt 的目录，优先 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates = [exe_dir, exe_dir.parent, Path.cwd()]
    else:
        candidates = [_APP_DIR.parent]
    result: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in result:
            result.append(resolved)
    return result


def _project_root_from(default: Path | None = None) -> Path:
    if default is not None:
        return Path(default)
    candidates = _candidate_project_roots()
    for candidate in candidates:
        if (candidate / "upload.ps1").is_file() and (candidate / "key.txt").is_file():
            return candidate
    for candidate in candidates:
        if (candidate / "upload.ps1").is_file() or (candidate / "key.txt").is_file():
            return candidate
    return candidates[0] if candidates else _APP_DIR.parent


def _make_icon() -> QIcon:
    icon_path = _APP_DIR / "assets" / "app.svg"
    icon = QIcon(str(icon_path))
    if not icon.isNull():
        return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QColor("#2F6FED"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawEllipse(16, 24, 26, 16)
    painter.end()
    return QIcon(pixmap)


def _install_exception_hook(app: QApplication, quiet: bool = False) -> None:
    def hook(exc_type, exc_value, exc_tb) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            if sys.stderr is not None:
                print(details, file=sys.stderr)
        except Exception:  # noqa: BLE001 - pythonw 下 stderr 可能不可用
            pass
        if quiet:
            app.exit(1)
            return
        try:
            box = QMessageBox()
            box.setWindowTitle(APP_NAME)
            box.setIcon(QMessageBox.Critical)
            box.setText("界面出现未处理的异常。请把下面的详细信息反馈给开发者。")
            box.setInformativeText(str(exc_value))
            box.setDetailedText(details)
            box.exec_()
        except Exception:  # noqa: BLE001 - 异常钩子里不能再抛
            pass

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="项目目录（默认是 dafeiyu_gui 的上一级目录；exe 模式下优先 exe 所在目录及上一级）",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    try:
        if sys.platform == "win32":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Dafeiyu.ControlPanel"
            )
    except Exception:  # noqa: BLE001 - 仅影响任务栏分组
        pass

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Dafeiyu")
    app.setStyle("Fusion")
    app.setWindowIcon(_make_icon())
    app.setFont(QFont("Microsoft YaHei UI", 9))
    _install_exception_hook(app, quiet=args.smoke_test)

    lock_path = Path(tempfile.gettempdir()) / "dafeiyu-gui.lock"
    lock = QLockFile(str(lock_path))
    if not lock.tryLock(150):
        if not args.smoke_test:
            QMessageBox.warning(
                None,
                APP_NAME,
                "已经有一个大肥鱼控制台在运行。\n为避免同时操作 key.txt 和服务器，本次启动已退出。",
            )
        return 1

    settings = QSettings("Dafeiyu", "ControlPanel")
    theme_name = str(settings.value("theme", "light") or "light")
    if theme_name not in theme.THEMES:
        theme_name = "light"
    theme.apply_theme(app, theme_name)

    root = _project_root_from(args.project_root).resolve()
    if not root.is_dir():
        if not args.smoke_test:
            QMessageBox.critical(None, APP_NAME, f"项目目录不存在：\n{root}")
        return 1

    # 输入法（例如搜狗）会在当前目录写 debug.log；启动后切到临时目录，
    # 避免把这类无关文件写进项目目录。项目路径已经解析为绝对路径。
    try:
        os.chdir(tempfile.gettempdir())
    except OSError:
        pass

    try:
        window = MainWindow(root, settings)
    except Exception as exc:  # noqa: BLE001
        details = traceback.format_exc()
        try:
            if sys.stderr is not None:
                print(details, file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass
        if not args.smoke_test:
            QMessageBox.critical(None, APP_NAME, f"无法创建主窗口：{exc}\n\n{details}")
        return 1
    window.show()
    if args.smoke_test:
        QTimer.singleShot(1200, app.quit)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
