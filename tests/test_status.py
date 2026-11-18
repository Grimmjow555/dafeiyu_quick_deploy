from __future__ import annotations

import json
import unittest

from tests.helpers import ROOT  # noqa: F401 - 确保项目根在 sys.path

from dafeiyu_gui.backend.status import parse_status


class StatusParserTests(unittest.TestCase):
    def test_running_online(self) -> None:
        text = (
            "NAME   IMAGE   SERVICE   STATUS\n"
            "QQ 掉线守护：active\n"
            "\nQQ / 守护进程状态：\n"
            "  QQ 状态：在线（账号 123456），loginPhase=5\n"
            "  守护进程记录：online，更新于 2026-11-18T01:00:00Z，恢复阶段 无\n"
            "  密码自动登录：已配置\n"
            "大肥鱼正在运行。\n"
        )
        report = parse_status(text)
        self.assertEqual(report.services, "running")
        self.assertEqual(report.qq, "online")
        self.assertEqual(report.watchdog, "active")
        self.assertIsNotNone(report.checked_at)

    def test_stopped(self) -> None:
        text = "QQ 掉线守护：inactive\n\n大肥鱼当前未运行，可执行 sudo bash start.sh 启动。\n"
        report = parse_status(text)
        self.assertEqual(report.services, "stopped")
        self.assertEqual(report.watchdog, "inactive")

    def test_needs_qr(self) -> None:
        text = (
            "QQ 掉线守护：active\n"
            "QQ 状态：未在线（loginPhase=1）\n"
            "守护进程记录：needs_qr，更新于 just now\n"
            "提示：等待扫码\n"
        )
        report = parse_status(text)
        self.assertEqual(report.qq, "needs_qr")
        self.assertEqual(report.watchdog, "active")

    def test_awaiting_login(self) -> None:
        text = (
            "QQ 状态：未在线（loginPhase=0）\n"
            "守护进程记录：awaiting_login，更新于 now\n"
        )
        report = parse_status(text)
        self.assertEqual(report.qq, "needs_qr")
        self.assertIn("等待", report.qq_detail)

    def test_verification_json(self) -> None:
        payload = {
            "checked_at_utc": "2026-11-18T01:00:00Z",
            "services_ready": True,
            "plugins_active": 9,
            "voice_requested": True,
            "voice_enabled": False,
            "voice_mode": "tts2",
            "voice_model": "seed-tts-2.0",
            "memory_enabled": True,
            "owner_configured": True,
            "qq_logged_in": False,
            "napcat_token_saved": True,
            "qq_delivery_tested": False,
            "napcat_auth_limited": True,
            "qq_watchdog_active": True,
            "qq_watchdog_status": "awaiting_login",
        }
        text = "部署输出\n" + json.dumps(payload, ensure_ascii=False) + "\n完成\n"
        report = parse_status(text)
        self.assertEqual(report.services, "running")
        self.assertEqual(report.watchdog, "active")
        self.assertEqual(report.qq, "needs_qr")
        self.assertEqual(report.plugins_active, 9)
        self.assertFalse(report.voice_enabled)
        self.assertTrue(report.memory_enabled)
        self.assertTrue(report.napcat_auth_limited)
        self.assertEqual(report.verification["voice_mode"], "tts2")

    def test_not_installed_and_unknown(self) -> None:
        report = parse_status("QQ 掉线守护：未安装\n")
        self.assertEqual(report.watchdog, "not_installed")
        self.assertEqual(report.services, "unknown")
        self.assertEqual(report.qq, "unknown")

    def test_auth_limited(self) -> None:
        report = parse_status("警告：NapCat WebUI 登录接口被限流，本次 QQ 状态取自守护进程。")
        self.assertTrue(report.napcat_auth_limited)


if __name__ == "__main__":
    unittest.main()
