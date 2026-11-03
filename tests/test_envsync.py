from __future__ import annotations

import os
import re
import stat
import unittest
from pathlib import Path

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import envsync

# Values here are made up and shaped like nothing a scanner looks for; they only need to be recognisable
# in output, so a test can prove that no command prints one.
VALUE = "zzz-" + "q" * 12
OTHER = "yyy-" + "w" * 12


def write(root: Path, name: str, text: str) -> Path:
    path = Path(root) / name
    path.write_bytes(text.encode("utf-8"))
    return path


def read(root: Path, name: str) -> str:
    return (Path(root) / name).read_bytes().decode("utf-8")


def mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(str(path)).st_mode)


class EnvCase(TempDirCase):
    def brain(self, example=None, env=None) -> Path:
        root = self.fake_brain()
        if example is not None:
            write(root, ".env.example", example)
        if env is not None:
            write(root, ".env", env)
        return root

    def env_sync(self, root, *args):
        return self.run_brain(root, "env-sync", *args)


class KeyPatternTest(unittest.TestCase):
    def test_key_pattern_is_pinned(self):
        self.assertEqual(envsync.KEY_RE, r"^[A-Za-z_][A-Za-z0-9_]*$")

    def test_key_pattern_accepts_names_and_nothing_else(self):
        for good in ("A", "_", "API_BASE_URL", "a1", "_9"):
            self.assertTrue(re.fullmatch(envsync.KEY_RE, good), good)
        for bad in ("", "1A", "A-B", "A B", "A=b", "A.B", "A\n", "\nA", "é", "A;B", "$A"):
            self.assertFalse(re.fullmatch(envsync.KEY_RE, bad), repr(bad))


class SyncTest(EnvCase):
    def test_env_sync_adds_missing_keys(self):
        example = "# Secret NAMES only.\n\nA_KEY=\nexport B_KEY=\nC_KEY\n# D_KEY=\nA_KEY=\n"
        root = self.brain(example=example, env=f"A_KEY={VALUE}\n")
        r = self.env_sync(root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(root, ".env"), f"A_KEY={VALUE}\nB_KEY=\nC_KEY=\n")   # in file order; the value untouched
        self.assertIn("B_KEY", r.stdout)
        self.assertIn("C_KEY", r.stdout)
        self.assertNotIn("D_KEY", r.stdout)       # commented out
        self.assertEqual(read(root, ".env.example"), example)   # the example is never edited by a plain sync

    def test_second_run_changes_nothing(self):
        root = self.brain(example="A_KEY=\nB_KEY=\n")
        self.assertEqual(self.env_sync(root).returncode, 0)
        first = read(root, ".env")
        r = self.env_sync(root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(root, ".env"), first)
        self.assertEqual(first, "A_KEY=\nB_KEY=\n")

    def test_creates_env_with_mode_600_even_under_a_lax_umask(self):
        root = self.brain(example="A_KEY=\n")
        old = os.umask(0)
        try:
            r = self.env_sync(root)
        finally:
            os.umask(old)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(root, ".env"), "A_KEY=\n")
        self.assertEqual(mode(root / ".env"), 0o600)

    def test_an_existing_env_keeps_its_mode(self):
        root = self.brain(example="A_KEY=\nB_KEY=\n", env="A_KEY=\n")
        (root / ".env").chmod(0o640)
        self.assertEqual(self.env_sync(root).returncode, 0)
        self.assertEqual(mode(root / ".env"), 0o640)

    def test_appends_after_a_missing_final_newline_and_keeps_crlf(self):
        root = self.brain(example="A_KEY=\nB_KEY=\n", env="A_KEY=1\r\nOTHER=2")
        self.assertEqual(self.env_sync(root).returncode, 0)
        self.assertEqual(read(root, ".env"), "A_KEY=1\r\nOTHER=2\r\nB_KEY=\r\n")

    def test_byte_order_mark_and_export_do_not_hide_a_key(self):
        root = self.brain(example="﻿A_KEY=\nB_KEY=\n", env="﻿A_KEY=1\nexport B_KEY=2\n")
        self.assertEqual(self.env_sync(root).returncode, 0)
        self.assertEqual(read(root, ".env"), "﻿A_KEY=1\nexport B_KEY=2\n")

    def test_no_example_is_not_an_error_and_creates_nothing(self):
        root = self.brain()
        r = self.env_sync(root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((root / ".env").exists())
        self.assertFalse((root / ".env.example").exists())

    def test_an_unreadable_env_is_a_refusal_that_names_no_value(self):
        root = self.brain(example="A_KEY=\n")
        (root / ".env").mkdir()    # a directory where the file should be
        r = self.env_sync(root)
        self.assertEqual(r.returncode, 1)
        self.assertIn(".env", r.stderr)


class NeverPrintsValuesTest(EnvCase):
    def test_never_prints_values(self):
        root = self.brain(example="A_KEY=\nB_KEY=\n", env=f"A_KEY={VALUE}\nEXTRA={OTHER}\n")
        runs = [(), ("--list",), ("--add", "A_KEY"), ("--add", "B_KEY"), ("--add", "NEW_KEY"),
                ("--add", f"A_KEY={VALUE}"), ("--add", f"bad key {VALUE}")]
        for args in runs:
            r = self.env_sync(root, *args)
            for value in (VALUE, OTHER):
                self.assertNotIn(value, r.stdout, args)
                self.assertNotIn(value, r.stderr, args)
        self.assertNotIn(VALUE, read(root, ".env.example"))   # and the example never gains one
        self.assertNotIn(OTHER, read(root, ".env.example"))


class AddTest(EnvCase):
    def test_add_key(self):
        root = self.brain(example="A_KEY=\n", env=f"A_KEY={VALUE}\n")
        r = self.env_sync(root, "--add", "NEW_KEY")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(root, ".env.example"), "A_KEY=\nNEW_KEY=\n")
        self.assertEqual(read(root, ".env"), f"A_KEY={VALUE}\nNEW_KEY=\n")
        self.assertIn("NEW_KEY", r.stdout)
        again = self.env_sync(root, "--add", "NEW_KEY")        # idempotent
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(read(root, ".env.example"), "A_KEY=\nNEW_KEY=\n")
        self.assertEqual(read(root, ".env"), f"A_KEY={VALUE}\nNEW_KEY=\n")

    def test_add_fills_only_what_is_absent(self):
        root = self.brain(example="A_KEY=\nB_KEY=\n", env=f"B_KEY={VALUE}\nC_KEY={OTHER}\n")
        self.assertEqual(self.env_sync(root, "--add", "C_KEY").returncode, 0)   # in .env, not in the example
        self.assertEqual(read(root, ".env.example"), "A_KEY=\nB_KEY=\nC_KEY=\n")
        self.assertEqual(read(root, ".env"), f"B_KEY={VALUE}\nC_KEY={OTHER}\n")
        self.assertEqual(self.env_sync(root, "--add", "A_KEY").returncode, 0)   # in the example, not in .env
        self.assertEqual(read(root, ".env.example"), "A_KEY=\nB_KEY=\nC_KEY=\n")
        self.assertEqual(read(root, ".env"), f"B_KEY={VALUE}\nC_KEY={OTHER}\nA_KEY=\n")

    def test_add_creates_both_files_when_neither_exists(self):
        root = self.brain()
        old = os.umask(0)
        try:
            r = self.env_sync(root, "--add", "FIRST_KEY")
        finally:
            os.umask(old)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(root, ".env.example"), "FIRST_KEY=\n")
        self.assertEqual(read(root, ".env"), "FIRST_KEY=\n")
        self.assertEqual(mode(root / ".env"), 0o600)

    def test_add_to_an_example_without_a_final_newline(self):
        root = self.brain(example="A_KEY=")
        self.assertEqual(self.env_sync(root, "--add", "B_KEY").returncode, 0)
        self.assertEqual(read(root, ".env.example"), "A_KEY=\nB_KEY=\n")

    def test_invalid_key(self):
        root = self.brain(example="A_KEY=\n", env="A_KEY=\n")
        before = self.snapshot(root)
        for bad in ("", "1ABC", "A-B", "bad key", "KEY=" + VALUE, "A\n", "é", "../x"):
            r = self.env_sync(root, "--add", bad)
            self.assertEqual(r.returncode, 2, repr(bad))
            self.assertNotIn(VALUE, r.stdout + r.stderr)
            self.assertNotIn("../x", r.stdout + r.stderr)    # a refused argument is not echoed
        self.assertEqual(self.snapshot(root), before)

    def test_add_and_list_together_are_a_usage_error(self):
        root = self.brain(example="A_KEY=\n")
        self.assertEqual(self.env_sync(root, "--add", "B_KEY", "--list").returncode, 2)
        self.assertFalse((root / ".env").exists())


class ListTest(EnvCase):
    def test_list(self):
        example = "A_KEY=\nB_KEY=\nC_KEY=\nD_KEY=\nE_KEY=\nF_KEY=\nG_KEY=\n"
        env = (f"A_KEY={VALUE}\nB_KEY=\nD_KEY=\"\"\nE_KEY='  '\nF_KEY= # a comment\nG_KEY=\"{OTHER}\" # kept\n"
               f"EXTRA={OTHER}\n")
        root = self.brain(example=example, env=env)
        before = self.snapshot(root)
        r = self.env_sync(root, "--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            "A_KEY  set", "B_KEY  empty", "C_KEY  missing", "D_KEY  empty", "E_KEY  empty", "F_KEY  empty",
            "G_KEY  set"])
        self.assertEqual(self.snapshot(root), before)   # listing writes nothing

    def test_list_without_an_env_says_everything_is_missing(self):
        root = self.brain(example="A_KEY=\nB_KEY=\n")
        r = self.env_sync(root, "--list")
        self.assertEqual(r.stdout.splitlines(), ["A_KEY  missing", "B_KEY  missing"])
        self.assertFalse((root / ".env").exists())

    def test_last_assignment_wins(self):
        root = self.brain(example="A_KEY=\n", env=f"A_KEY=\nA_KEY={VALUE}\n")
        self.assertEqual(self.env_sync(root, "--list").stdout.splitlines(), ["A_KEY  set"])


if __name__ == "__main__":
    unittest.main()
