from __future__ import annotations

import codecs
import unittest

from tests.helpers import (
    make_scratch_dir,
    remove_scratch_dir,
    sample_key_text,
    write_sample_key,
)

from dafeiyu_gui.backend import keyfile


class KeyFileParseTests(unittest.TestCase):
    def test_comment_url_and_unknown_fields(self) -> None:
        text = (
            "# 注释\n"
            "\n"
            "SSH_HOST=203.0.113.9\n"
            "CUSTOM_FIELD=keep-me\n"
            "ASTRBOT: http://203.0.113.9:6185/\n"
            "NapCat:  http://203.0.113.9:6099/webui/web_login\n"
        )
        values, errors, urls = keyfile.parse_key_lines(text.splitlines())
        self.assertEqual(errors, [])
        self.assertEqual(values["SSH_HOST"], "203.0.113.9")
        self.assertEqual(values["CUSTOM_FIELD"], "keep-me")
        self.assertIn("AstrBot", urls)
        self.assertIn("NapCat", urls)

    def test_value_can_contain_equals_and_hash(self) -> None:
        values, errors, _ = keyfile.parse_key_lines(["KEY=a=b#c"])
        self.assertEqual(errors, [])
        self.assertEqual(values["KEY"], "a=b#c")

    def test_duplicate_and_invalid_lines(self) -> None:
        values, errors, _ = keyfile.parse_key_lines(
            ["SSH_HOST=a", "SSH_HOST=b", "BAD_LINE", "=nohost"]
        )
        self.assertEqual(values["SSH_HOST"], "a")
        self.assertEqual(len(errors), 3)

    def test_read_crlf_and_bom(self) -> None:
        root = make_scratch_dir()
        try:
            path = root / "key.txt"
            write_sample_key(path, crlf=True, bom=True)
            doc = keyfile.read_key_file(path)
            self.assertTrue(doc.has_bom)
            self.assertEqual(doc.newline, "\r\n")
            self.assertEqual(doc.parse_errors, [])
            self.assertEqual(doc.get("SSH_HOST"), "203.0.113.9")
        finally:
            remove_scratch_dir(root)

    def test_update_preserves_order_comments_crlf_and_url_lines(self) -> None:
        root = make_scratch_dir()
        try:
            path = root / "key.txt"
            write_sample_key(path, crlf=True)
            doc = keyfile.read_key_file(path)
            new_doc = keyfile.write_key_file(
                doc,
                {
                    "DEEPSEEK_MODEL": "deepseek-chat",
                    "DOUBAO_API_KEY": "synthetic-voice-key",
                    "NAPCAT_TOKEN": "synthetic-token",
                },
            )
            raw = path.read_bytes()
            self.assertNotIn(b"\xef\xbb\xbf", raw[:3])
            self.assertIn(b"\r\n", raw)
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
            text = raw.decode("utf-8")
            self.assertIn("# 测试用合成配置", text)
            self.assertIn("DEEPSEEK_MODEL=deepseek-chat", text)
            self.assertIn("DOUBAO_API_KEY=synthetic-voice-key", text)
            self.assertIn("NAPCAT_TOKEN=synthetic-token", text)
            self.assertTrue(text.rstrip().endswith("/webui/web_login"))
            self.assertEqual(new_doc.get("DEEPSEEK_MODEL"), "deepseek-chat")
            self.assertEqual(new_doc.values["ASTRBOT_USERNAME"], "admin")
        finally:
            remove_scratch_dir(root)

    def test_update_preserves_unknown_field_and_comment(self) -> None:
        root = make_scratch_dir()
        try:
            path = root / "key.txt"
            path.write_text(
                "# head\nUNKNOWN_KEEP=1\nSSH_HOST=old.example\n# tail\n",
                encoding="utf-8",
            )
            doc = keyfile.read_key_file(path)
            keyfile.write_key_file(doc, {"SSH_HOST": "new.example", "ASTRBOT_PASSWORD": "Abcdef12"})
            text = path.read_text(encoding="utf-8")
            self.assertIn("UNKNOWN_KEEP=1", text)
            self.assertIn("# head", text)
            self.assertIn("# tail", text)
            self.assertIn("SSH_HOST=new.example", text)
        finally:
            remove_scratch_dir(root)

    def test_validation_rules(self) -> None:
        values = {
            "SSH_HOST": "bad host",
            "SSH_USER": "Bad User",
            "SSH_PASSWORD": "x",
            "DEEPSEEK_API_KEY": "k",
            "ASTRBOT_USERNAME": "admin",
            "ASTRBOT_PASSWORD": "short",
            "OWNER_QQ": "abc",
            "DOUBAO_API_KEY": "key:abc",
            "DOUBAO_SPEAKER": "bad speaker",
        }
        issues = keyfile.validate_values(values)
        fields = {issue.field for issue in issues}
        for expected in (
            "SSH_HOST",
            "SSH_USER",
            "ASTRBOT_PASSWORD",
            "OWNER_QQ",
            "DOUBAO_API_KEY",
            "DOUBAO_SPEAKER",
        ):
            self.assertIn(expected, fields)

    def test_required_and_derived_helpers(self) -> None:
        values = {
            "SSH_HOST": "203.0.113.9",
            "SSH_USER": "root",
            "SSH_PASSWORD": "x",
            "DEEPSEEK_API_KEY": "k",
            "ASTRBOT_USERNAME": "admin",
            "ASTRBOT_PASSWORD": "Abcdef12",
        }
        self.assertEqual(keyfile.missing_required(values), [])
        self.assertEqual(keyfile.voice_mode(values), "none")
        self.assertTrue(keyfile.service_urls(values)["AstrBot"].startswith("http://203.0.113.9:6185"))
        legacy = dict(values)
        legacy["DOUBAO_APP_ID"] = "app"
        legacy["DOUBAO_ACCESS_TOKEN"] = "token"
        self.assertEqual(keyfile.voice_mode(legacy), "seed_audio")
        legacy["DOUBAO_API_KEY"] = "new"
        self.assertEqual(keyfile.voice_mode(legacy), "tts2")
        self.assertTrue(keyfile.memory_configured({**values, "SILICONFLOW_API_KEY": "sf"}))

    def test_bom_round_trip(self) -> None:
        root = make_scratch_dir()
        try:
            path = root / "key.txt"
            text = "# bom\nSSH_HOST=a.example\n"
            path.write_bytes(codecs.BOM_UTF8 + text.encode("utf-8"))
            doc = keyfile.read_key_file(path)
            keyfile.write_key_file(doc, {"SSH_HOST": "b.example"})
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(codecs.BOM_UTF8))
            self.assertIn(b"SSH_HOST=b.example", raw)
        finally:
            remove_scratch_dir(root)

    def test_missing_file_raises_readable_error(self) -> None:
        root = make_scratch_dir()
        try:
            with self.assertRaises(keyfile.KeyFileError):
                keyfile.read_key_file(root / "missing.txt")
        finally:
            remove_scratch_dir(root)

    def test_render_sample_text_unchanged_when_no_updates(self) -> None:
        text = sample_key_text(crlf=False)
        values, errors, _ = keyfile.parse_key_lines(text.splitlines())
        self.assertEqual(errors, [])
        self.assertEqual(values["SSH_USER"], "root")


if __name__ == "__main__":
    unittest.main()
