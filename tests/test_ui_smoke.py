from __future__ import annotations

import os
import time
import unittest
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
from PyQt5.QtWidgets import QApplication, QDialog, QLineEdit, QWidget  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
