from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import make_scratch_dir, remove_scratch_dir

from dafeiyu_gui import app as app_module


class FrozenProjectRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_scratch_dir()
        (self.root / "upload.ps1").write_text("# fake\n", encoding="utf-8")
        (self.root / "key.txt").write_text("SSH_HOST=203.0.113.9\n", encoding="utf-8")
        self.dist = self.root / "dist"
        self.dist.mkdir()

    def tearDown(self) -> None:
        remove_scratch_dir(self.root)

    def test_exe_inside_project_root(self) -> None:
        exe = self.root / "大肥鱼控制台.exe"
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "executable", str(exe)
        ):
            found = app_module._project_root_from()
        self.assertEqual(found.resolve(), self.root.resolve())

    def test_exe_in_dist_finds_parent_project(self) -> None:
        exe = self.dist / "大肥鱼控制台.exe"
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "executable", str(exe)
        ):
            found = app_module._project_root_from()
        self.assertEqual(found.resolve(), self.root.resolve())

    def test_explicit_project_root_wins(self) -> None:
        explicit = self.root / "dist"
        self.assertEqual(app_module._project_root_from(explicit), explicit)

    def test_missing_project_files_falls_back_to_exe_dir(self) -> None:
        fallback = self.root / "fallback"
        fallback.mkdir()
        empty = fallback / "empty"
        empty.mkdir()
        exe = empty / "tool.exe"
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "executable", str(exe)
        ), mock.patch.object(Path, "cwd", return_value=empty):
            found = app_module._project_root_from()
        self.assertEqual(found.resolve(), empty.resolve())


if __name__ == "__main__":
    unittest.main()
