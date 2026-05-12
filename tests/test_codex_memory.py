from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from codex_memory.config import load_config
from codex_memory.init_project import init_project


class CodexMemoryTests(unittest.TestCase):
    def test_load_config_from_project_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            (root / ".codex-memory.toml").write_text(
                'project_id = "demo-project"\nproject_name = "Demo Project"\n',
                encoding="utf-8",
            )
            args = argparse.Namespace(project_root=str(root))
            config = load_config(args)
            self.assertEqual(config.project_id, "demo-project")
            self.assertEqual(config.project_name, "Demo Project")
            self.assertEqual(config.project_root, root.resolve())

    def test_init_project_creates_config_and_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            args = argparse.Namespace(project_root=str(root), project_id="demo", project_name="demo")
            config = load_config(args)
            written = init_project(config, force=False, wrapper_name="run_codex")
            written_names = {path.name for path in written}
            self.assertIn(".codex-memory.toml", written_names)
            self.assertIn("run_codex.sh", written_names)
            self.assertIn("run_codex.cmd", written_names)
            self.assertIn("run_codex.ps1", written_names)

            config_text = (root / ".codex-memory.toml").read_text(encoding="utf-8")
            self.assertIn('project_id = "demo"', config_text)
            self.assertIn('{storage_root}/demo/{machine}', config_text)

            shell_wrapper = (root / "run_codex.sh").read_text(encoding="utf-8")
            self.assertTrue(shell_wrapper.startswith("#!/usr/bin/env bash"))
            self.assertIn('${BASH_SOURCE[0]}', shell_wrapper)


if __name__ == "__main__":
    unittest.main()
