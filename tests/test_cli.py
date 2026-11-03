from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest

from tests.helpers import TEMPLATE_ROOT, VERSION, TempDirCase

META = TEMPLATE_ROOT / "_meta"


def harness_files():
    return sorted([*META.rglob("*.py"), META / "brain"])


class CliTest(TempDirCase):
    def test_version(self):
        r = self.run_brain(TEMPLATE_ROOT, "--version")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, f"brain {VERSION}"))

    def test_unknown_command_is_usage_error(self):
        r = self.run_brain(TEMPLATE_ROOT, "nope")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: brain", r.stderr)  # argparse said so; python failing to open the script also exits 2

    def test_no_command_is_usage_error(self):
        r = self.run_brain(TEMPLATE_ROOT)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: brain", r.stderr)

    def test_entry_point_is_executable_python_script(self):
        brain = META / "brain"
        self.assertTrue(os.access(brain, os.X_OK))
        self.assertEqual(brain.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env python3")

    def test_runs_from_a_symlink_and_a_foreign_cwd(self):
        # The entry point finds brainlib next to its real path, whatever the cwd is.
        link = self.tmp / "brain-link"
        link.symlink_to(META / "brain")
        r = subprocess.run([sys.executable, str(link), "--version"], cwd=str(self.tmp), env=self.env,
                           capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, f"brain {VERSION}"))

    def test_run_does_not_write_bytecode(self):
        # Without PYTHONDONTWRITEBYTECODE, only the entry point itself keeps the brain free of __pycache__.
        root = self.fake_brain()
        env = {k: v for k, v in self.env.items() if k != "PYTHONDONTWRITEBYTECODE"}
        r = subprocess.run([sys.executable, str(root / "_meta" / "brain"), "--version"], cwd=str(root), env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(list(root.rglob("__pycache__")), [])

    def test_harness_parses_as_python_3_9(self):
        for p in harness_files():
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p), feature_version=(3, 9))

    def test_every_harness_module_starts_with_future_annotations(self):
        for p in harness_files():
            body = ast.parse(p.read_text(encoding="utf-8"), filename=str(p)).body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]  # skip the module docstring
            first = body[0] if body else None
            self.assertTrue(
                isinstance(first, ast.ImportFrom) and first.module == "__future__"
                and [a.name for a in first.names] == ["annotations"],
                f"{p} must start with `from __future__ import annotations`",
            )

    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "needs Python 3.10+ for sys.stdlib_module_names")
    def test_stdlib_only(self):
        allowed = set(sys.stdlib_module_names) | {"brainlib"}
        for p in harness_files():
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"), filename=str(p))):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                for name in names:
                    self.assertIn(name, allowed, f"{p} imports {name}")


if __name__ == "__main__":
    unittest.main()
