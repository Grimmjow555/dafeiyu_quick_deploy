from __future__ import annotations

import unittest

from tests.helpers import ROOT  # noqa: F401 - 确保项目根在 sys.path

from dafeiyu_gui.backend.redact import PLACEHOLDER, Redactor, is_sensitive_field


class RedactorTests(unittest.TestCase):
    def test_sensitive_fields(self) -> None:
        for name in (
            "SSH_PASSWORD",
            "DEEPSEEK_API_KEY",
            "NAPCAT_TOKEN",
            "QQ_WATCHDOG_WEBHOOK",
        ):
            self.assertTrue(is_sensitive_field(name))
        self.assertFalse(is_sensitive_field("SSH_HOST"))
        self.assertFalse(is_sensitive_field("OWNER_QQ"))

    def test_redacts_values(self) -> None:
        redactor = Redactor(
            {
                "SSH_PASSWORD": "secret-password",
                "DEEPSEEK_API_KEY": "sk-secret-key",
                "SSH_HOST": "203.0.113.9",
            }
        )
        text = "连接 203.0.113.9，密码 secret-password，Key=sk-secret-key"
        result = redactor.redact(text)
        self.assertNotIn("secret-password", result)
        self.assertNotIn("sk-secret-key", result)
        self.assertIn("203.0.113.9", result)
        self.assertEqual(result.count(PLACEHOLDER), 2)

    def test_short_values_are_not_over_redacted(self) -> None:
        redactor = Redactor({"SSH_PASSWORD": "abc", "DEEPSEEK_API_KEY": "k"})
        self.assertFalse(redactor)
        self.assertEqual(redactor.redact("abc k"), "abc k")

    def test_refresh(self) -> None:
        redactor = Redactor({"SSH_PASSWORD": "old-secret"})
        self.assertNotIn("old-secret", redactor.redact("old-secret"))
        redactor.refresh({"SSH_PASSWORD": "new-secret"})
        self.assertNotIn("new-secret", redactor.redact("new-secret"))
        self.assertIn("old-secret", redactor.redact("old-secret"))

    def test_longer_values_win(self) -> None:
        redactor = Redactor({"A_TOKEN": "abcdef", "B_PASSWORD": "abcdefgh"})
        self.assertEqual(redactor.redact("abcdefgh"), PLACEHOLDER)


if __name__ == "__main__":
    unittest.main()
