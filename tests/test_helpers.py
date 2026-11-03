from __future__ import annotations

import json
import os
import unittest

from tests.helpers import TempDirCase


class HelpersTest(TempDirCase):
    def test_tmp_has_a_space_and_env_is_hermetic(self):
        self.assertIn(" ", str(self.tmp))
        self.assertEqual(self.env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(self.env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(self.env["TMPDIR"], str(self.tmp / "os-tmp"))
        self.assertEqual(os.path.getsize(self.env["GIT_CONFIG_GLOBAL"]), 0)
        self.assertTrue((self.tmp / "os-tmp").is_dir())
        self.assertEqual(self.git(self.tmp, "config", "--global", "--list"), "")

    def test_git_identity_and_failure(self):
        repo = self._new_dir("repo")
        self.git(repo, "init", "-q")
        (repo / "f").write_text("x", encoding="utf-8")
        self.git(repo, "add", "f")
        self.git(repo, "commit", "-q", "-m", "m")
        self.assertEqual(self.git(repo, "log", "-1", "--format=%an <%ae>").strip(), "Brain Test <test@example.invalid>")
        with self.assertRaises(AssertionError):
            self.git(repo, "no-such-subcommand")

    def test_fake_brain_holds_harness_and_minimal_config(self):
        root = self.fake_brain(prefix="ab", role="template", extra={"gates": []})
        self.assertTrue((root / "_meta" / "brain").is_file())
        self.assertTrue((root / "_meta" / "brainlib" / "cli.py").is_file())
        self.assertEqual(list(root.rglob("__pycache__")), [])
        raw = json.loads((root / "brain.json").read_text(encoding="utf-8"))
        self.assertEqual((raw["prefix"], raw["role"], raw["gates"]), ("ab", "template", []))
        self.assertNotIn("role", json.loads((self.fake_brain() / "brain.json").read_text(encoding="utf-8")))

    def test_run_brain_uses_the_given_root(self):
        root = self.fake_brain()
        r = self.run_brain(root, "--version", cwd=self.tmp)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "brain 0.1.0"))

    def test_make_skill_writes_frontmatter(self):
        root = self.fake_brain()
        path = self.make_skill(root, "lab-a", "Does X. Use when Y.", "# Body")
        self.assertEqual(path, root / ".claude" / "skills" / "lab-a" / "SKILL.md")
        self.assertEqual(path.read_text(encoding="utf-8"),
                         "---\nname: lab-a\ndescription: Does X. Use when Y.\n---\n# Body\n")

    def test_snapshot_sees_content_additions_and_git_internals(self):
        repo = self._new_dir("snap")
        self.git(repo, "init", "-q")
        (repo / "a.txt").write_text("one", encoding="utf-8")
        before = self.snapshot(repo)
        self.assertEqual(self.snapshot(repo), before)
        self.assertIn("a.txt", before)
        self.assertEqual(before["a.txt"][0], 3)
        self.assertTrue(any(k.startswith(".git/") for k in before))
        self.git(repo, "add", "a.txt")
        self.assertIn(".git/index", self.snapshot(repo))
        self.assertNotEqual(self.snapshot(repo), before)
        (repo / "a.txt").write_text("three", encoding="utf-8")
        self.assertEqual(self.snapshot(repo)["a.txt"][0], 5)

    def test_copy_template_is_a_committed_repo_without_scratch(self):
        copy = self.copy_template()
        self.assertEqual(self.git(copy, "rev-parse", "--abbrev-ref", "HEAD").strip(), "main")
        self.assertEqual(len(self.git(copy, "rev-list", "HEAD").split()), 1)
        self.assertEqual(self.git(copy, "status", "--porcelain"), "")
        self.assertTrue((copy / "_meta" / "brain").is_file())
        self.assertTrue(os.access(copy / "_meta" / "brain", os.X_OK))
        self.assertTrue((copy / "local").is_dir())
        self.assertEqual(list((copy / "local").iterdir()), [])
        for scratch in (".superpowers", ".brain-private"):
            self.assertFalse((copy / scratch).exists(), scratch)
        self.assertFalse((self.copy_template(with_local=False) / "local").exists())

    def test_copy_tree_leaves_out_ignored_files_in_a_git_source(self):
        src = self._new_dir("src")
        self.git(src, "init", "-q")
        (src / ".gitignore").write_text("/*\n!/.gitignore\n!/keep/\n!/new/\n", encoding="utf-8")
        for rel in ("keep/tracked.txt", "new/untracked.txt", "local/notes.txt", ".superpowers/x", ".brain-private"):
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text("x", encoding="utf-8")
        self.git(src, "add", ".gitignore", "keep/tracked.txt")
        gone = src / "keep" / "gone.txt"
        gone.write_text("x", encoding="utf-8")
        self.git(src, "add", "keep/gone.txt")
        gone.unlink()  # tracked but deleted in the working tree: skipped, not an error
        dest = self._new_dir("dest")
        self._copy_tree(src, dest)
        self.assertEqual(sorted(self.snapshot(dest)),
                         [".gitignore", "keep/tracked.txt", "new/untracked.txt"])

    def test_copy_tree_without_git_skips_scratch(self):
        src = self._new_dir("plain")
        for rel in ("a.txt", "sub/b.txt", "sub/local/c.txt", "local/n.txt", ".superpowers/x", "sub/.git/HEAD",
                    "sub/__pycache__/m.pyc"):
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text("x", encoding="utf-8")
        dest = self._new_dir("dest")
        self._copy_tree(src, dest)
        self.assertEqual(sorted(self.snapshot(dest)), ["a.txt", "sub/b.txt", "sub/local/c.txt"])


if __name__ == "__main__":
    unittest.main()
