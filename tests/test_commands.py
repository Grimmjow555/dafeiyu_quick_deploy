from __future__ import annotations

import unittest

from tests.helpers import ROOT  # noqa: F401 - 确保项目根在 sys.path

from dafeiyu_gui.backend import commands


class CommandBuilderTests(unittest.TestCase):
    def test_switch_is_not_quoted(self) -> None:
        command = commands.build_inner_command(r"C:\项目\upload.ps1", ["-Status"])
        self.assertIn("-Status", command)
        self.assertNotIn("'-Status'", command)
        self.assertIn("& 'C:\\项目\\upload.ps1'", command)
        self.assertIn("[Console]::OutputEncoding", command)

    def test_start_array_literal(self) -> None:
        arguments = commands.build_action_arguments("start", start_no_wait=True)
        self.assertEqual(arguments, ["-Start", "-StartArgs", "--no-wait"])
        command = commands.build_inner_command("upload.ps1", arguments)
        self.assertIn("-StartArgs @('--no-wait')", command)

    def test_stop_array_literal(self) -> None:
        arguments = commands.build_action_arguments(
            "stop", stop_down=True, stop_timeout=120
        )
        self.assertEqual(
            arguments, ["-Stop", "-StopArgs", "--down", "--timeout", "120"]
        )
        command = commands.build_inner_command("upload.ps1", arguments)
        self.assertIn("-StopArgs @('--down','--timeout','120')", command)

    def test_stop_dry_run(self) -> None:
        arguments = commands.build_action_arguments("stop", stop_dry_run=True)
        self.assertEqual(arguments, ["-Stop", "-StopArgs", "--dry-run"])
        self.assertIn("-StopArgs @('--dry-run')", commands.build_inner_command("u.ps1", arguments))

    def test_stop_args_validation(self) -> None:
        with self.assertRaises(ValueError):
            commands.make_stop_args(timeout=-1)
        with self.assertRaises(ValueError):
            commands.make_stop_args(timeout=3601)
        self.assertEqual(commands.make_stop_args(timeout=0), ["--timeout", "0"])

    def test_unknown_action(self) -> None:
        with self.assertRaises(ValueError):
            commands.build_action_arguments("nope")

    def test_path_quote_escaping(self) -> None:
        command = commands.build_inner_command("C:\\a'b\\upload.ps1", [])
        self.assertIn("C:\\a''b\\upload.ps1", command)

    def test_display_has_no_secret_and_reads_well(self) -> None:
        text = commands.display_command("stop", ["-Stop", "-StopArgs", "--dry-run"])
        self.assertTrue(text.startswith("upload.ps1 -Stop"))
        self.assertNotIn("PASSWORD", text)

    def test_all_actions_build(self) -> None:
        for action in commands.ACTIONS:
            arguments = commands.build_action_arguments(action.key)
            self.assertIsInstance(arguments, list)
            argv = commands.build_process_argv("upload.ps1", arguments)
            self.assertEqual(argv[0].lower().endswith("powershell.exe"), True)
            self.assertIn("-Command", argv)


if __name__ == "__main__":
    unittest.main()
