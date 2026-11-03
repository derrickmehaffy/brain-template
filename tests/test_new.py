from __future__ import annotations

import json
import os
import re
import stat
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config, hook, install, managed, manifest


class NewCase(TempDirCase):
    def new(self, template, dest, *extra, name="homelab", prefix="lab", description="Running my lab"):
        args = ["new", str(dest), "--name", name, "--prefix", prefix]
        if description is not None:
            args += ["--description", description]
        return self.run_brain(template, *args, *extra)

    def made(self, *extra, **kwargs):
        """(the template copy, the brain folder) after a `new` that must succeed."""
        template = self.copy_template()
        dest = self.tmp / "my brain"
        r = self.new(template, dest, *extra, **kwargs)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return template, dest

    def version_of(self, template) -> str:
        return (template / "_meta" / "VERSION").read_text(encoding="utf-8").strip()

    def read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))


class CreateTest(NewCase):
    def test_new_creates_working_brain(self):
        template, dest = self.made()
        version = self.version_of(template)

        raw = self.read_json(dest / "brain.json")
        self.assertEqual(raw["name"], "homelab")
        self.assertEqual(raw["prefix"], "lab")
        self.assertEqual(raw["description"], "Running my lab")
        self.assertIsNone(raw["template"]["source"])  # the template is not published, so there is no canonical source
        self.assertRegex(raw["template"]["version"], "^" + re.escape(version) + r"\+[0-9a-f]{7,}$")
        self.assertEqual(raw["scripts"], {"python": "python3", "packages": "stdlib-only"})
        self.assertEqual(raw["privacy"], {"deny_patterns": [], "max_file_kb": 1024, "large_file_allow": []})
        self.assertEqual(raw["practices"], {"stale_after_days": 180})
        self.assertEqual((raw["gates"], raw["gates_off"]), ([], []))
        cfg = config.load(dest)
        self.assertEqual(cfg.role, "brain")

        local = self.read_json(dest / "brain.local.json")
        self.assertEqual(local, {"template": {"source": str(template)}})
        self.assertEqual(config.effective_source(cfg), str(template))

        claude_md = (dest / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(claude_md.startswith(managed.MD_BEGIN + "\n"))
        self.assertIn(managed.MD_END, claude_md)
        self.assertIn("# homelab\n\nRunning my lab\n", claude_md)
        self.assertNotIn("{{", claude_md)
        self.assertTrue((dest / ".gitignore").read_text(encoding="utf-8").startswith(managed.GI_BEGIN + "\n"))
        self.assertIn("# homelab", (dest / "README.md").read_text(encoding="utf-8"))
        self.assertIn("`lab-<name>`", (dest / "README.md").read_text(encoding="utf-8"))

        settings = self.read_json(dest / ".claude" / "settings.json")
        self.assertEqual(settings["permissions"]["deny"], managed.DENY)
        pre = settings["hooks"]["PreToolUse"][0]
        post = settings["hooks"]["PostToolUse"][0]
        self.assertEqual(pre["hooks"][0]["command"], '"$CLAUDE_PROJECT_DIR/_meta/brain" gate check')
        self.assertEqual(post["hooks"][0]["command"], '"$CLAUDE_PROJECT_DIR/_meta/brain" gate record')

        for rel in ("docs/README.md", "docs/ROUTING.md", "docs/CAPABILITIES.md", "docs/RETRO-LOG.md",
                    "docs/UNCLASSIFIED-LOG.md", "docs/UPSTREAM.md", "docs/practices/README.md",
                    "docs/practices/INDEX.md", "scripts/README.md", "scripts/tests/__init__.py", ".env.example",
                    "README.md", "_meta/brain", "_meta/VERSION", "_meta/ROUTING-META.md", "_meta/gates.json"):
            self.assertTrue((dest / rel).is_file(), rel)
        self.assertTrue(os.access(dest / "_meta" / "brain", os.X_OK))
        self.assertFalse(os.access(dest / "README.md", os.X_OK))

        recorded = manifest.read(dest)
        self.assertIn("_meta/brain", recorded)
        self.assertNotIn("README.md", recorded)  # brain-owned, so not in the manifest
        self.assertNotIn("docs/ROUTING.md", recorded)
        self.assertEqual(manifest.local_edits(dest), [])

        # nothing of the template's own comes along
        for rel in ("tests", "local", "docs/superpowers", ".worktrees", ".superpowers"):
            self.assertFalse((dest / rel).exists(), rel)
        self.assertEqual(sorted(p.name for p in (dest / ".claude" / "skills").glob("template-*")), [])
        self.assertTrue(list((dest / ".claude" / "skills").glob("brain-*")))

        # one commit, the pinned message, and a clean tree
        subjects = self.git(dest, "log", "--format=%s").splitlines()
        self.assertEqual(subjects, [f"meta(brain): initialise from template v{raw['template']['version']}"])
        self.assertEqual(self.git(dest, "status", "--porcelain"), "")
        tracked = self.git(dest, "ls-files").splitlines()
        self.assertIn("brain.json", tracked)
        self.assertIn(".claude/settings.json", tracked)
        self.assertIn("docs/practices/INDEX.md", tracked)
        for private in ("brain.local.json", ".brain-private", ".env"):
            self.assertNotIn(private, tracked)

        # the pre-commit guard is installed
        shim = dest / ".git" / "hooks" / "pre-commit"
        self.assertEqual(shim.read_text(encoding="utf-8"), hook.SHIM)
        self.assertTrue(os.access(shim, os.X_OK))

        r = self.run_brain(dest, "lint")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        listed = (template / "local" / "brains.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(listed, [str(dest)])

    def test_make_brain_helper_and_the_guard_in_a_template_copy(self):
        brain = self.make_brain()
        self.assertEqual(self.read_json(brain / "brain.json")["name"], "homelab")
        self.assertEqual(self.read_json(brain / "brain.json")["prefix"], "lab")
        self.assertEqual(len(self.git(brain, "rev-list", "HEAD").split()), 1)
        self.assertEqual(self.read_json(self.make_brain("other", "oth") / "brain.json")["prefix"], "oth")
        template = self.copy_template()  # the real template has its own guard, so its copy does too
        self.assertEqual((template / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8"), hook.SHIM)

    def test_new_ignores_git_variables_that_name_another_repository(self):
        template = self.copy_template()
        before = self.git(template, "rev-parse", "HEAD")
        dest = self.tmp / "my brain"
        self.env["GIT_DIR"] = str(template / ".git")
        self.env["GIT_WORK_TREE"] = str(template)
        try:
            r = self.new(template, dest)
        finally:
            del self.env["GIT_DIR"], self.env["GIT_WORK_TREE"]
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.git(template, "rev-parse", "HEAD"), before)
        self.assertEqual(self.git(template, "status", "--porcelain"), "")
        self.assertTrue((dest / ".git").is_dir())
        self.assertEqual(len(self.git(dest, "rev-list", "HEAD").split()), 1)

    def test_new_ends_with_the_next_step(self):
        template = self.copy_template()
        dest = self.tmp / "my brain"
        r = self.new(template, dest)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.rstrip("\n").splitlines()[-1], f"open a session in {dest}")

    def test_the_new_brain_commits_through_its_own_guard(self):
        _, dest = self.made()
        (dest / "docs" / "note.md").write_text("a note\n", encoding="utf-8")
        self.git(dest, "add", "docs/note.md")
        self.git(dest, "commit", "-q", "-m", "docs: a note")
        self.assertEqual(len(self.git(dest, "rev-list", "HEAD").split()), 2)

    def test_creates_missing_parent_folders_and_accepts_an_empty_folder(self):
        template = self.copy_template()
        deep = self.tmp / "a" / "b" / "brain"
        self.assertEqual(self.new(template, deep).returncode, 0)
        self.assertTrue((deep / "brain.json").is_file())
        empty = self.tmp / "empty one"
        empty.mkdir()
        self.assertEqual(self.new(template, empty, prefix="lab2", name="two").returncode, 0)
        self.assertTrue((empty / "brain.json").is_file())
        listed = (template / "local" / "brains.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(listed, [str(deep), str(empty)])

    def test_register_adds_a_brain_once(self):
        template = self.copy_template()
        brain = self.tmp / "brain one"
        brain.mkdir()
        install.register(template, brain)
        install.register(template, brain)
        other = self.tmp / "brain two"
        other.mkdir()
        install.register(template, other)
        listed = (template / "local" / "brains.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(listed, [str(brain), str(other)])

    def test_register_creates_local_and_keeps_an_unterminated_last_line(self):
        template = self.copy_template(with_local=False)
        brain = self.tmp / "brain one"
        install.register(template, brain)
        listing = template / "local" / "brains.txt"
        self.assertEqual(listing.read_text(encoding="utf-8"), f"{brain}\n")
        listing.write_text("/somewhere/else", encoding="utf-8")  # no trailing newline
        install.register(template, brain)
        self.assertEqual(listing.read_text(encoding="utf-8"), f"/somewhere/else\n{brain}\n")


class RefusalTest(NewCase):
    def refused(self, template, dest, *extra, **kwargs):
        before_template = self.snapshot(template)
        before_dest = self.snapshot(dest) if dest.exists() else None
        r = self.new(template, dest, *extra, **kwargs)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.snapshot(template), before_template)  # not even local/brains.txt
        if before_dest is None:
            self.assertFalse(dest.exists())
        else:
            self.assertEqual(self.snapshot(dest), before_dest)
        return r

    def test_refuses_non_empty_dir(self):
        template = self.copy_template()
        dest = self.tmp / "busy"
        dest.mkdir()
        (dest / "notes.txt").write_text("mine\n", encoding="utf-8")
        r = self.refused(template, dest)
        self.assertIn("not empty", r.stderr)
        self.assertIn("adopt", r.stderr)
        for entry in (".git", ".hidden"):  # a hidden entry counts as content
            with self.subTest(entry=entry):
                other = self.tmp / ("busy-" + entry.strip("."))
                other.mkdir()
                (other / entry).mkdir()
                self.assertIn("not empty", self.refused(template, other).stderr)

    def test_refuses_a_file_as_the_folder(self):
        template = self.copy_template()
        dest = self.tmp / "a file"
        dest.write_text("x", encoding="utf-8")
        self.assertIn("not a folder", self.refused(template, dest).stderr)

    def test_refuses_bad_and_reserved_prefix(self):
        template = self.copy_template()
        for prefix in ("brain", "template", "A", "x", "Lab", "1abc", "a-b", "a_b", "a" * 17, "lab "):
            with self.subTest(prefix=prefix):
                r = self.refused(template, self.tmp / "p", prefix=prefix)
                self.assertIn("prefix", r.stderr)
        self.assertEqual(self.new(template, self.tmp / "ok", prefix="a" + "b" * 15).returncode, 0)

    def test_refuses_outside_template(self):
        brain = self.fake_brain(prefix="lab")  # role is absent from its brain.json: a brain
        dest = self.tmp / "child"
        r = self.refused(brain, dest)
        self.assertIn("template checkout", r.stderr)
        explicit = self.fake_brain(prefix="lab", role="brain")
        self.assertIn("template checkout", self.refused(explicit, dest).stderr)

    def test_refuses_a_name_or_description_that_is_not_one_line(self):
        template = self.copy_template()
        self.assertIn("name", self.refused(template, self.tmp / "n", name="two\nlines").stderr)
        self.assertIn("name", self.refused(template, self.tmp / "n", name="  ").stderr)
        self.assertIn("description", self.refused(template, self.tmp / "n", description="one\r\ntwo").stderr)

    def test_refuses_when_the_template_has_no_commit(self):
        template = self.copy_template()
        self.git(template, "update-ref", "-d", "refs/heads/main")
        r = self.refused(template, self.tmp / "brain")
        self.assertIn("commit", r.stderr)

    def test_refuses_when_git_hooks_path_is_set(self):
        # Git would never run the guard in a brain made under this setting, so say so before writing anything.
        template = self.copy_template()
        self.git(template, "config", "--file", self.env["GIT_CONFIG_GLOBAL"], "core.hooksPath", "elsewhere")
        r = self.refused(template, self.tmp / "brain")
        self.assertIn("core.hooksPath", r.stderr)

    def test_a_usage_error_exits_2(self):
        template = self.copy_template()
        for args in (["new", str(self.tmp / "b"), "--prefix", "lab"],  # no --name
                     ["new", str(self.tmp / "b"), "--name", "x"],  # no --prefix
                     ["new", "--name", "x", "--prefix", "lab"],  # no folder
                     ["new", str(self.tmp / "b"), "--name", "x", "--prefix", "lab", "--packages", "maybe"]):
            with self.subTest(args=args):
                self.assertEqual(self.run_brain(template, *args).returncode, 2)
        self.assertFalse((self.tmp / "b").exists())

    def test_a_malformed_managed_file_is_a_message_not_a_traceback(self):
        # The skeleton's .gitignore is brain-owned text the managed block is merged into.
        template = self.copy_template()
        skeleton = template / "_meta" / "skeleton" / "gitignore"
        skeleton.write_text(managed.GI_BEGIN + "\n/*\n", encoding="utf-8")  # a begin marker with no end
        self.git(template, "add", "-A")
        self.git(template, "commit", "-q", "-m", "break the skeleton")
        r = self.new(template, self.tmp / "brain")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn(".gitignore", r.stderr)
        self.assertIn("begin marker", r.stderr)


class TemplateSourceTest(NewCase):
    def test_uses_committed_template_only(self):
        template = self.copy_template()
        committed_map = (template / "_meta" / "ROUTING-META.md").read_text(encoding="utf-8")
        committed_doc = (template / "_meta" / "skeleton" / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8")
        # uncommitted edits, an untracked shipped file and an untracked skeleton file: none may reach the brain
        (template / "_meta" / "ROUTING-META.md").write_text(committed_map + "\nuncommitted\n", encoding="utf-8")
        (template / "_meta" / "skeleton" / "docs" / "CAPABILITIES.md").write_text("changed\n", encoding="utf-8")
        (template / "_meta" / "stray.txt").write_text("untracked\n", encoding="utf-8")
        (template / "_meta" / "skeleton" / "docs" / "STRAY.md").write_text("untracked\n", encoding="utf-8")
        (template / "_meta" / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        dest = self.tmp / "brain"
        r = self.new(template, dest)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((dest / "_meta" / "ROUTING-META.md").read_text(encoding="utf-8"), committed_map)
        self.assertEqual((dest / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8"), committed_doc)
        self.assertFalse((dest / "_meta" / "stray.txt").exists())
        self.assertFalse((dest / "docs" / "STRAY.md").exists())
        self.assertNotIn("9.9.9", self.read_json(dest / "brain.json")["template"]["version"])
        self.assertTrue(self.read_json(dest / "brain.json")["template"]["version"].startswith("0.1.0+"))

    def test_the_template_checkout_is_left_as_it_was(self):
        template = self.copy_template()
        (template / "local" / "notes.txt").write_text("keep\n", encoding="utf-8")
        before = self.snapshot(template)
        dest = self.tmp / "brain"
        self.assertEqual(self.new(template, dest).returncode, 0)
        after = self.snapshot(template)
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        self.assertEqual(changed, ["local/brains.txt"])

    def test_template_source_follows_the_templates_own_when_published(self):
        template = self.copy_template()
        raw = self.read_json(template / "brain.json")
        raw["template"]["source"] = "https://example.invalid/template.git"
        (template / "brain.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        dest = self.tmp / "brain"
        self.assertEqual(self.new(template, dest).returncode, 0)
        self.assertEqual(self.read_json(dest / "brain.json")["template"]["source"], "https://example.invalid/template.git")
        # this machine's override still points at the checkout
        self.assertEqual(self.read_json(dest / "brain.local.json")["template"]["source"], str(template))

    def test_a_template_that_is_not_a_repo_is_read_from_its_working_tree(self):
        template = self.copy_template()
        plain = self._new_dir("plain")
        self._copy_tree(template, plain)  # no .git
        (plain / "local").mkdir()
        (plain / "local" / "brains.txt").write_text("", encoding="utf-8")
        dest = self.tmp / "brain"
        r = self.new(plain, dest)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_json(dest / "brain.json")["template"]["version"], self.version_of(plain))
        self.assertEqual(self.git(dest, "log", "--format=%s").splitlines(),
                         [f"meta(brain): initialise from template v{self.version_of(plain)}"])


class DryRunTest(NewCase):
    def test_dry_run_writes_nothing(self):
        template = self.copy_template()
        dest = self.tmp / "brain"
        before = self.snapshot(template)
        r = self.new(template, dest, "--dry-run", "--private", "acme")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.snapshot(template), before)
        self.assertFalse(dest.exists())
        lines = {line.strip() for line in r.stdout.splitlines() if line.startswith("  ")}  # the file list
        for rel in ("brain.json", "brain.local.json", "CLAUDE.md", ".gitignore", ".env.example", ".brain-private",
                    ".claude/settings.json", "_meta/brain", "_meta/MANIFEST.sha256", "docs/ROUTING.md",
                    "docs/practices/INDEX.md", "scripts/tests/__init__.py"):
            self.assertIn(rel, lines)
        self.assertFalse(any(line.startswith("tests/") or "template-" in line for line in lines), r.stdout)
        self.assertNotIn("open a session in", r.stdout)
        self.assertIn(str(dest), r.stdout)

    def test_dry_run_leaves_an_empty_folder_empty_and_still_refuses(self):
        template = self.copy_template()
        empty = self.tmp / "empty"
        empty.mkdir()
        self.assertEqual(self.new(template, empty, "--dry-run").returncode, 0)
        self.assertEqual(list(empty.iterdir()), [])
        (empty / "x").write_text("x", encoding="utf-8")
        self.assertEqual(self.new(template, empty, "--dry-run").returncode, 1)
        self.assertEqual(self.new(template, self.tmp / "q", "--dry-run", prefix="brain").returncode, 1)


class PrivateTest(NewCase):
    def test_private_patterns(self):
        template, dest = self.made("--private", "acme-corp", "--private", r"10\.20\.\d+\.\d+")
        private = dest / ".brain-private"
        lines = [line for line in private.read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
        self.assertEqual(lines, ["acme-corp", r"10\.20\.\d+\.\d+"])
        self.assertEqual(config.load(dest).private_patterns, ["acme-corp", r"10\.20\.\d+\.\d+"])
        self.assertTrue(self.read_json(dest / "brain.json")["privacy"]["private_file_expected"])
        self.assertNotIn(".brain-private", self.git(dest, "ls-files"))
        self.assertEqual(self.git(dest, "status", "--porcelain"), "")
        self.assertEqual(stat.S_IMODE(os.stat(str(private)).st_mode), 0o600)
        # and the guard it feeds is live from the first commit
        (dest / "docs" / "leak.md").write_text("see the acme-corp network\n", encoding="utf-8")
        self.git(dest, "add", "docs/leak.md")
        r = self.run_brain(dest, "hook", "pre-commit")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("private-pattern", r.stdout + r.stderr)

    def test_no_private_file_without_patterns(self):
        _, dest = self.made()
        self.assertFalse((dest / ".brain-private").exists())
        self.assertNotIn("private_file_expected", self.read_json(dest / "brain.json")["privacy"])

    def test_refuses_a_pattern_that_cannot_work(self):
        template = self.copy_template()
        before = self.snapshot(template)
        for pattern in ("(unclosed", "# a comment", "   ", "two\nlines"):
            with self.subTest(pattern=pattern):
                r = self.new(template, self.tmp / "p", "--private", pattern)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("--private", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertFalse((self.tmp / "p").exists())
        self.assertEqual(self.snapshot(template), before)

    def test_a_pattern_the_brain_itself_matches_stops_at_the_first_commit_and_says_why(self):
        # The guard reads the staged skeleton too; a term that names the brain would block its own first commit.
        template = self.copy_template()
        dest = self.tmp / "brain"
        r = self.new(template, dest, "--private", "homelab")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("private-pattern", r.stderr)
        self.assertIn("first commit", r.stderr)
        self.assertNotIn("open a session in", r.stdout)
        self.assertEqual(self.git(dest, "rev-list", "--all"), "")  # no commit was made
        self.assertFalse((template / "local" / "brains.txt").exists()
                         and str(dest) in (template / "local" / "brains.txt").read_text(encoding="utf-8"))


class ScriptsConfigTest(NewCase):
    def test_python_and_packages_flags(self):
        _, dest = self.made("--python", ".venv/bin/python", "--packages", "allowed")
        raw = self.read_json(dest / "brain.json")
        self.assertEqual(raw["scripts"], {"python": ".venv/bin/python", "packages": "allowed"})
        cfg = config.load(dest)
        self.assertEqual((cfg.python, cfg.packages), (".venv/bin/python", "allowed"))

    def test_defaults(self):
        _, dest = self.made(description=None)
        raw = self.read_json(dest / "brain.json")
        self.assertEqual(raw["description"], "")
        self.assertEqual(raw["scripts"], {"python": "python3", "packages": "stdlib-only"})


class InstallHelpersTest(NewCase):
    def test_fill_replaces_known_placeholders_once(self):
        out = install.fill(b"# {{name}} ({{prefix}})\n{{description}}\n{{other}}\n",
                           {"name": "a {{prefix}}", "prefix": "lab", "description": "d"})
        self.assertEqual(out, b"# a {{prefix}} (lab)\nd\n{{other}}\n")  # a value is never expanded again
        self.assertEqual(install.fill("é {{name}}".encode("utf-8"), {"name": "ü"}), "é ü".encode("utf-8"))
        self.assertEqual(install.fill(b"\xff\xfe{{name}}", {"name": "x"}), b"\xff\xfex")

    def test_shipped_and_skeleton_split(self):
        files = {
            "_meta/brain": (b"x", 0o755),
            "_meta/skeleton/gitignore": (b"g", 0o644),
            "_meta/skeleton/env.example": (b"e", 0o644),
            "_meta/skeleton/claude-settings.json": (b"{}", 0o644),
            "_meta/skeleton/docs/README.md": (b"d", 0o644),
            "_meta/skeleton/CLAUDE.md": (b"c", 0o644),
            "_meta/MANIFEST.sha256": (b"", 0o644),
            "_meta/brainlib/__pycache__/x.pyc": (b"", 0o644),
            ".claude/skills/brain-retro/SKILL.md": (b"s", 0o644),
            ".claude/skills/template-intake/SKILL.md": (b"s", 0o644),
            ".claude/skills/lab-own/SKILL.md": (b"s", 0o644),
            "tests/test_x.py": (b"t", 0o644),
            "CLAUDE.md": (b"template", 0o644),
            "brain.json": (b"{}", 0o644),
            "docs/design.md": (b"d", 0o644),
        }
        self.assertEqual(sorted(install.shipped(files)),
                         [".claude/skills/brain-retro/SKILL.md", "_meta/brain", "_meta/skeleton/CLAUDE.md",
                          "_meta/skeleton/claude-settings.json", "_meta/skeleton/docs/README.md",
                          "_meta/skeleton/env.example", "_meta/skeleton/gitignore"])
        self.assertNotIn(".claude/skills/template-intake/SKILL.md", install.shipped(files))
        self.assertEqual(install.shipped(files)["_meta/brain"], (b"x", 0o755))
        skeleton = install.skeleton(files)
        self.assertEqual(sorted(skeleton),
                         [".claude/settings.json", ".env.example", ".gitignore", "CLAUDE.md", "docs/README.md"])
        self.assertEqual(skeleton[".gitignore"], (b"g", 0o644))

    def test_write_tree_skips_existing_unless_overwrite_and_keeps_mode(self):
        dest = self._new_dir("tree")
        (dest / "kept.txt").write_text("mine", encoding="utf-8")
        files = {"kept.txt": (b"theirs", 0o644), "sub dir/run.sh": (b"#!/bin/sh\n", 0o755),
                 "sub dir/deeper/data.txt": (b"data", 0o644)}
        written = install.write_tree(dest, files, overwrite=False)
        self.assertEqual(written, ["sub dir/deeper/data.txt", "sub dir/run.sh"])
        self.assertEqual((dest / "kept.txt").read_text(encoding="utf-8"), "mine")
        self.assertTrue(os.access(dest / "sub dir" / "run.sh", os.X_OK))
        self.assertFalse(os.access(dest / "sub dir" / "deeper" / "data.txt", os.X_OK))
        again = install.write_tree(dest, files, overwrite=True)
        self.assertEqual(again, ["kept.txt", "sub dir/deeper/data.txt", "sub dir/run.sh"])
        self.assertEqual((dest / "kept.txt").read_text(encoding="utf-8"), "theirs")
        leftovers = [p.name for p in dest.rglob("*") if p.name.endswith(".brain-new")]
        self.assertEqual(leftovers, [])

    def test_write_tree_refuses_paths_that_leave_the_folder(self):
        dest = self._new_dir("tree")
        for rel in ("../escape.txt", "a/../../escape.txt", "/abs.txt", "a//b.txt", "./x.txt"):
            with self.subTest(rel=rel):
                with self.assertRaises(install.InstallError):
                    install.write_tree(dest, {rel: (b"x", 0o644)}, overwrite=True)
        self.assertEqual(list(dest.iterdir()), [])
        self.assertFalse((dest.parent / "escape.txt").exists())

    def test_template_files_without_git_leaves_out_scratch(self):
        src = self._new_dir("plain")
        for rel in ("a.txt", "sub/b.txt", "local/n.txt", ".git/HEAD", "sub/__pycache__/m.pyc", "_meta/brain"):
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text("x", encoding="utf-8")
        os.chmod(str(src / "_meta" / "brain"), 0o755)
        (src / "link.txt").symlink_to("a.txt")
        files = install.template_files(src)
        self.assertEqual(sorted(files), ["_meta/brain", "a.txt", "sub/b.txt"])
        self.assertEqual(files["_meta/brain"][1], 0o755)
        self.assertEqual(files["a.txt"], (b"x", 0o644))

    def test_template_files_in_a_repo_reads_head(self):
        src = self._new_dir("repo")
        self.git(src, "init", "-q")
        (src / "kept.txt").write_text("committed", encoding="utf-8")
        self.git(src, "add", "kept.txt")
        self.git(src, "commit", "-q", "-m", "one")
        (src / "kept.txt").write_text("edited", encoding="utf-8")
        (src / "new.txt").write_text("untracked", encoding="utf-8")
        with mock.patch.dict(os.environ, self.env, clear=True):
            files = install.template_files(src)
        self.assertEqual(files, {"kept.txt": (b"committed", 0o644)})

    def test_version_string(self):
        plain = self._new_dir("plain")
        (plain / "_meta").mkdir()
        (plain / "_meta" / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(install.version_string(plain), "1.2.3")
            self.git(plain, "init", "-q")
            self.git(plain, "add", "-A")
            self.git(plain, "commit", "-q", "-m", "one")
            sha = self.git(plain, "rev-parse", "--short", "HEAD").strip()
            self.assertEqual(install.version_string(plain), f"1.2.3+{sha}")
            (plain / "_meta" / "VERSION").write_text("2.0.0\n", encoding="utf-8")  # uncommitted: not the version
            self.assertEqual(install.version_string(plain), f"1.2.3+{sha}")

    def test_version_string_outside_a_repo_ignores_a_repo_above(self):
        outer = self._new_dir("outer")
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.git(outer, "init", "-q")
            (outer / "f").write_text("x", encoding="utf-8")
            self.git(outer, "add", "f")
            self.git(outer, "commit", "-q", "-m", "one")
            inner = outer / "inner"
            (inner / "_meta").mkdir(parents=True)
            (inner / "_meta" / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            self.assertEqual(install.version_string(inner), "1.0.0")

    def test_new_brain_json_shape_and_order(self):
        raw = install.new_brain_json("homelab", "lab", "d", None, "0.1.0+abc1234", "python3", "stdlib-only", False)
        self.assertEqual(list(raw), ["name", "prefix", "description", "template", "scripts", "privacy",
                                     "practices", "gates", "gates_off"])
        self.assertEqual(raw["template"], {"source": None, "version": "0.1.0+abc1234"})
        self.assertNotIn("private_file_expected", raw["privacy"])
        raw = install.new_brain_json("n", "pp", "", "https://x.invalid/t.git", "1", ".venv/bin/python", "allowed", True)
        self.assertTrue(raw["privacy"]["private_file_expected"])
        self.assertEqual(raw["scripts"], {"python": ".venv/bin/python", "packages": "allowed"})


class ApplyManagedTest(NewCase):
    def meta(self):
        """A folder holding the template's managed blocks, as a brain's `_meta/managed` does."""
        dest = self._new_dir("managed")
        (dest / "_meta" / "managed").mkdir(parents=True)
        for name in ("CLAUDE.block.md", "gitignore.block"):
            (dest / "_meta" / "managed" / name).write_bytes(
                (Path(__file__).resolve().parent.parent / "_meta" / "managed" / name).read_bytes())
        return dest

    def test_creates_the_three_files_when_absent(self):
        dest = self.meta()
        self.assertEqual(install.apply_managed(dest), [])
        self.assertTrue((dest / "CLAUDE.md").read_text(encoding="utf-8").startswith(managed.MD_BEGIN))
        self.assertTrue((dest / ".gitignore").read_text(encoding="utf-8").startswith(managed.GI_BEGIN))
        settings = self.read_json(dest / ".claude" / "settings.json")
        self.assertEqual(settings["permissions"]["deny"], managed.DENY)

    def test_keeps_the_brains_own_text_and_is_idempotent(self):
        dest = self.meta()
        (dest / "CLAUDE.md").write_bytes(b"# mine\r\n\r\nrules\r\n")
        (dest / ".gitignore").write_text("/own/\n", encoding="utf-8")
        (dest / ".claude").mkdir()
        (dest / ".claude" / "settings.json").write_text(
            json.dumps({"permissions": {"deny": ["Bash(rm -rf *)"], "allow": ["Read"]}, "model": "x"}), encoding="utf-8")
        install.apply_managed(dest)
        first = {rel: (dest / rel).read_bytes() for rel in ("CLAUDE.md", ".gitignore", ".claude/settings.json")}
        self.assertTrue(first["CLAUDE.md"].endswith(b"\r\n\r\n# mine\r\n\r\nrules\r\n"))  # CRLF kept
        self.assertTrue(first[".gitignore"].endswith(b"\n\n/own/\n"))
        settings = json.loads(first[".claude/settings.json"])
        self.assertEqual(settings["permissions"]["deny"], ["Bash(rm -rf *)", *managed.DENY])
        self.assertEqual((settings["permissions"]["allow"], settings["model"]), (["Read"], "x"))
        install.apply_managed(dest)
        self.assertEqual({rel: (dest / rel).read_bytes() for rel in first}, first)

    def test_invalid_settings_json_is_a_warning_and_the_file_is_left(self):
        dest = self.meta()
        (dest / ".claude").mkdir()
        (dest / ".claude" / "settings.json").write_text("{ not json", encoding="utf-8")
        warnings = install.apply_managed(dest)
        self.assertEqual(len(warnings), 1)
        self.assertIn(".claude/settings.json", warnings[0])
        self.assertEqual((dest / ".claude" / "settings.json").read_text(encoding="utf-8"), "{ not json")
        self.assertTrue((dest / "CLAUDE.md").is_file())  # the other two are still set

    def test_malformed_input_raises_managed_error_and_writes_nothing(self):
        dest = self.meta()
        (dest / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
        (dest / ".gitignore").write_text(managed.GI_BEGIN + "\n/*\n", encoding="utf-8")  # no end marker
        with self.assertRaises(managed.ManagedError) as caught:
            install.apply_managed(dest)
        self.assertIn(".gitignore", str(caught.exception))
        self.assertEqual((dest / "CLAUDE.md").read_text(encoding="utf-8"), "# mine\n")  # not half-applied

        for bad in ('[]', '{"hooks": []}', '{"permissions": {"deny": "x"}}'):
            with self.subTest(settings=bad):
                other = self.meta()
                (other / ".claude").mkdir()
                (other / ".claude" / "settings.json").write_text(bad, encoding="utf-8")
                with self.assertRaises(managed.ManagedError):
                    install.apply_managed(other)
                self.assertFalse((other / "CLAUDE.md").exists())
                self.assertEqual((other / ".claude" / "settings.json").read_text(encoding="utf-8"), bad)

    def test_write_private_keeps_existing_lines(self):
        dest = self._new_dir("private")
        install.write_private(dest, ["one", "two"])
        install.write_private(dest, ["two", "three"])
        lines = [x for x in (dest / ".brain-private").read_text(encoding="utf-8").splitlines() if not x.startswith("#")]
        self.assertEqual(lines, ["one", "two", "three"])
        (dest / "brain.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(config.load(dest).private_patterns, lines)


class GitStepsTest(NewCase):
    def test_git_init_and_first_commit(self):
        dest = self._new_dir("repo")
        (dest / "f.txt").write_text("x\n", encoding="utf-8")
        with mock.patch.dict(os.environ, self.env, clear=True):
            install.git_init(dest)
            sha = install.first_commit(dest, "meta(brain): hello")
            self.assertRegex(sha, "^[0-9a-f]{7,}$")
            self.assertEqual(self.git(dest, "rev-parse", "--short", "HEAD").strip(), sha)
            self.assertEqual(self.git(dest, "log", "--format=%s").splitlines(), ["meta(brain): hello"])


if __name__ == "__main__":
    unittest.main()
