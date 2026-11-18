from __future__ import annotations

import os
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")
if os.name == "nt" and Path(r"C:\Windows\Fonts").is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from tests.helpers import (  # noqa: E402 - 先设置 Qt 环境
    fake_upload_script,
    make_scratch_dir,
    remove_scratch_dir,
    write_sample_key,
)

from PyQt5.QtCore import QSettings  # noqa: E402
from PyQt5.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QWidget  # noqa: E402

from dafeiyu_gui.backend.status import StatusReport  # noqa: E402
from dafeiyu_gui.ui import dialogs, theme  # noqa: E402
from dafeiyu_gui.ui.main_window import MainWindow  # noqa: E402


class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        theme.apply_theme(cls.app, "light")

    def setUp(self) -> None:
        self.root = make_scratch_dir()
        self.script = self.root / "upload.ps1"
        self.script.write_text(fake_upload_script(), encoding="utf-8-sig")
        self.key_path = self.root / "key.txt"
        write_sample_key(self.key_path, crlf=True)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.IniFormat)
        self.window = MainWindow(self.root, self.settings)

    def tearDown(self) -> None:
        try:
            self.window.close()
            self.app.processEvents()
        finally:
            remove_scratch_dir(self.root)

    def _pump_until_idle(self, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        while self.window._busy and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()

    def test_window_state_and_masking(self) -> None:
        self.window.show()
        self.app.processEvents()
        self.assertEqual(self.window.stack.count(), 3)
        self.assertEqual(len(self.window.settings_page._editors), 16)
        password_editor = self.window.settings_page._editors["SSH_PASSWORD"]
        self.assertEqual(password_editor.echoMode(), QLineEdit.Password)
        self.assertTrue(self.window.overview.deploy_button.isEnabled())
        self.assertEqual(sorted(self.window.overview._urls), ["AstrBot", "NapCat"])
        self.assertIn("203.0.113.9", self.window.server_chip.text())
        self.assertIn("203.0.113.9", self.window.windowTitle())
        log_text = self.window.overview.log_view.text()
        for secret in ("secret-ssh-password", "sk-test-deepseek-secret"):
            self.assertNotIn(secret, log_text)

    def test_save_preserves_crlf_and_updates_value(self) -> None:
        editor = self.window.settings_page._editors["DEEPSEEK_MODEL"]
        editor.setText("deepseek-chat")
        self.assertTrue(self.window.settings_page.is_dirty())
        self.assertTrue(self.window._save_config(show_message=False))
        raw = self.key_path.read_bytes()
        self.assertIn(b"DEEPSEEK_MODEL=deepseek-chat", raw)
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertFalse(self.window.settings_page.is_dirty())
        self.assertEqual(self.window.doc.get("DEEPSEEK_MODEL"), "deepseek-chat")
        self.assertNotIn("secret-ssh-password", self.window.overview.log_view.text())

    def test_status_action_updates_cards_and_redacts(self) -> None:
        self.window.show()
        self.app.processEvents()
        self.window._begin_action("status", {})
        self._pump_until_idle()
        self.assertFalse(self.window._busy)
        self.assertEqual(self.window.status_report.services, "running")
        self.assertEqual(self.window.status_report.qq, "online")
        self.assertEqual(self.window.status_report.watchdog, "active")
        log_text = self.window.overview.log_view.text()
        self.assertNotIn("secret-ssh-password", log_text)
        self.assertIn("<已隐藏>", log_text)

    def test_theme_toggle(self) -> None:
        self.window._toggle_theme()
        self.assertEqual(self.settings.value("theme"), "dark")
        self.assertIn("#0F1522", self.app.styleSheet())
        self.window._toggle_theme()
        self.assertEqual(self.settings.value("theme"), "light")

    def test_host_key_prompt_sends_yes(self) -> None:
        self.script.write_text(
            "param([switch]$Status)\n"
            "Write-Host 'SSH server: 203.0.113.9:22'\n"
            "Write-Host 'The saved key differs. Verify this fingerprint.'\n"
            "$answer = Read-Host 'Type YES'\n"
            "Write-Host ('answer=' + $answer)\n"
            "Write-Host '大肥鱼正在运行。'\n"
            "exit 0\n",
            encoding="utf-8-sig",
        )
        with mock.patch.object(
            dialogs.HostKeyDialog, "exec_", return_value=QDialog.Accepted
        ):
            self.window._begin_action("status", {})
            self._pump_until_idle()
        log_text = self.window.overview.log_view.text()
        self.assertFalse(self.window._busy)
        self.assertIn("已发送主机密钥确认（YES）", log_text)
        self.assertIn("answer=YES", log_text)
        self.assertFalse(self.window._host_canceled)

    def test_restored_small_geometry_is_clamped(self) -> None:
        probe = QWidget()
        probe.resize(640, 480)
        self.settings.setValue("geometry", probe.saveGeometry())
        probe.deleteLater()
        second = MainWindow(self.root, self.settings)
        try:
            second.show()
            self.app.processEvents()
            self.assertGreaterEqual(second.width(), second.minimumWidth())
            self.assertGreaterEqual(second.height(), second.minimumHeight())
        finally:
            second.close()
            self.app.processEvents()

    def test_finish_operation_keeps_result_visible(self) -> None:
        self.window.show()
        self.window._select_page(0)
        self.app.processEvents()
        self.window.overview.begin_operation("一键部署 / 更新", True)
        self.window.overview.finish_operation(True, "部署 / 更新完成", "success")
        self.app.processEvents()
        self.assertFalse(self.window.overview.progress_panel.isVisible())
        self.assertTrue(self.window.overview.result_bar.isVisible())
        self.assertEqual(self.window.overview.result_bar._text.text(), "部署 / 更新完成")

    def test_stop_action_refreshes_checked_hint(self) -> None:
        self.window.overview.apply_report(
            StatusReport(services="running", checked_at=datetime(2020, 1, 1, 3, 4, 5))
        )
        before = self.window.overview._status_hint.text()
        self.window._apply_action_status("stop", {}, "")
        after = self.window.overview._status_hint.text()
        self.assertNotEqual(before, after)
        self.assertIn("本地停止操作", after)
        self.assertEqual(self.window.overview.status_board.services._value.text(), "已停止")

    def test_status_detail_is_elided_with_full_tooltip(self) -> None:
        self.window.show()
        self.window._select_page(0)
        self.window.resize(1000, 700)
        self.app.processEvents()
        card = self.window.overview.status_board.qq
        full = "账号 10001 · loginPhase=5 · 掉线守护恢复正常 · 最近一次快速登录成功"
        card.set_state("在线", "ok", full)
        self.app.processEvents()
        self.assertTrue(card._detail.text().endswith("…"), card._detail.text())
        self.assertNotEqual(card._detail.text(), full)
        self.assertEqual(card._detail.toolTip(), full)

    def test_settings_filter_rebuilds_rows(self) -> None:
        self.window.show()
        self.window._select_page(1)
        self.app.processEvents()
        page = self.window.settings_page
        rows = {spec.name: box for spec, _holder, box, _hay in page._field_rows}
        page.search_edit.setText("token")
        self.app.processEvents()
        self.assertTrue(rows["SSH_HOST"].isHidden())
        self.assertFalse(rows["NAPCAT_TOKEN"].isHidden())
        self.assertTrue(page._group_cards["服务器"].isHidden())
        self.assertFalse(page._group_cards["高级"].isHidden())
        page.search_edit.clear()
        self.app.processEvents()
        self.assertFalse(rows["SSH_HOST"].isHidden())
        self.assertFalse(page._group_cards["服务器"].isHidden())

    def test_required_fields_are_marked(self) -> None:
        page = self.window.settings_page
        self.assertEqual(page._field_labels["SSH_HOST"].text(), "服务器地址")
        marks = [
            label.text()
            for label in page.findChildren(QLabel)
            if label.objectName() == "RequiredMark"
        ]
        self.assertEqual(marks.count("*"), 6)


if __name__ == "__main__":
    unittest.main()
