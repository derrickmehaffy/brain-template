from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import TEMPLATE_ROOT, VERSION, TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import cmd_init, config, hook, managed, manifest

CANONICAL = "https://example.invalid/brain-template.git"
CANONICAL_GH = "https://github.com/example/brain-template.git"
STUB_SKILL = "brain-stubby"
STAND_IN = "template-only stand-in"
HISTORY = ".brain/template-history.git"


class InitCase(TempDirCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, self.env, clear=True)  # in-process git calls stay hermetic
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- fixtures ---------------------------------------------------------

    def template_copy(self, source=None) -> Path:
        """A committed copy of the template without `local/`, holding a stand-in for each template-only file the
        working tree does not have yet (README.md, CLAUDE.md, .claude/settings.json), and `source` as its
        canonical `template.source` when given."""
        copy = self.copy_template(with_local=False)
        for rel in ("README.md", "CLAUDE.md", ".claude/settings.json"):
            if not (copy / rel).exists():
                (copy / rel).parent.mkdir(parents=True, exist_ok=True)
                (copy / rel).write_text(STAND_IN + "\n" if rel != ".claude/settings.json" else "{}\n",
                                        encoding="utf-8")
        self.make_skill(copy, STUB_SKILL, "A stand-in shipped skill for tests. Use when a test needs one. Does NOT "
                        "replace brain-sync.", "Does nothing.\n\n## Done when\n\n- nothing is left to do")
        synced = self.run_brain(copy, "routing", "sync")  # the guard refuses a skill whose reserved outputs are stale
        self.assertEqual(synced.returncode, 0, synced.stdout + synced.stderr)
        if source is not None:
            raw = self.read_json(copy / "brain.json")
            raw["template"]["source"] = source
            (copy / "brain.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        self.git(copy, "add", "-A")
        self.git(copy, "commit", "-q", "-m", "stand-ins for the template-only files")
        return copy

    def plain_clone(self, source=None):
        """(the template copy, a `git clone` of it): origin is the template, so this is a plain clone."""
        template = self.template_copy(source)
        clone = self._new_dir("clone")
        self.git(self.tmp, "clone", "-q", str(template), str(clone))
        return template, clone

    def used_template(self, source=None, url="https://example.invalid/me/mybrain.git") -> Path:
        """A repo made the "Use this template" way: the template's files as the first commit of a new history,
        with the person's own remote."""
        template = self.template_copy(source)
        dest = self._new_dir("used")
        self._copy_tree(template, dest)
        self.git(dest, "init", "-q")
        self.git(dest, "symbolic-ref", "HEAD", "refs/heads/main")
        self.git(dest, "add", "-A")
        self.git(dest, "commit", "-q", "-m", "Initial commit")
        self.git(dest, "remote", "add", "origin", url)
        return dest

    def bare_folder(self, source=None) -> Path:
        """A copy of the template with no repository at all."""
        copy = self.template_copy(source)
        shutil.rmtree(str(copy / ".git"))
        return copy

    def init(self, root, *extra, name="homelab", prefix="lab", description="Running my lab", cwd=None):
        args = ["init", "--name", name, "--prefix", prefix]
        if description is not None:
            args += ["--description", description]
        return self.run_brain(root, *args, *extra, cwd=cwd)

    def assert_no_scratch_left(self):
        """The OS temporary folder (TMPDIR of the test) holds nothing: the rehearsal copy was removed."""
        self.assertEqual(os.listdir(str(self.tmp / "os-tmp")), [])

    def refused(self, root, *extra, message=None, **kwargs):
        """Run init, expect a refusal that changed nothing, and return its stderr."""
        before = self.snapshot(root)
        listing = sorted(os.listdir(str(root)))
        r = self.init(root, *extra, **kwargs)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertTrue(r.stderr.startswith("init: "), r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.snapshot(root), before)
        self.assertEqual(sorted(os.listdir(str(root))), listing)
        self.assert_no_scratch_left()
        if message:
            self.assertIn(message, r.stderr)
        return r.stderr

    def done(self, root, *extra, **kwargs):
        r = self.init(root, *extra, **kwargs)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assert_no_scratch_left()
        return r

    @staticmethod
    def read_json(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def version_of(root) -> str:
        return (Path(root) / "_meta" / "VERSION").read_text(encoding="utf-8").strip()

    def commits(self, root):
        return self.git(root, "log", "--format=%s").splitlines()

    def assert_a_brain(self, root, template_version):
        """What every route ends in: no template-only file, the shipped files, the skeleton, a clean tree."""
        self.assertFalse((root / "tests").exists())
        self.assertFalse((root / "docs" / "superpowers").exists())
        self.assertEqual(sorted(p.name for p in (root / ".claude" / "skills").glob("template-*")), [])
        self.assertTrue((root / ".claude" / "skills" / STUB_SKILL / "SKILL.md").is_file())  # a shipped skill stays
        self.assertIn(f".claude/skills/{STUB_SKILL}/SKILL.md", manifest.read(root))
        for rel in ("_meta/brain", "_meta/VERSION", "_meta/skeleton/CLAUDE.md", "docs/README.md", "docs/ROUTING.md",
                    "docs/practices/INDEX.md", "scripts/tests/__init__.py", ".env.example"):
            self.assertTrue((root / rel).is_file(), rel)
        for rel in ("README.md", "CLAUDE.md", ".claude/settings.json", ".gitignore", "brain.json"):
            self.assertNotIn(STAND_IN, (root / rel).read_text(encoding="utf-8"), rel)
        self.assertIn("# homelab", (root / "README.md").read_text(encoding="utf-8"))
        claude_md = (root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(claude_md.startswith(managed.MD_BEGIN + "\n"))
        self.assertIn("# homelab\n\nRunning my lab\n", claude_md)
        self.assertTrue((root / ".gitignore").read_text(encoding="utf-8").startswith(managed.GI_BEGIN + "\n"))
        settings = self.read_json(root / ".claude" / "settings.json")
        self.assertEqual(settings["permissions"]["deny"], managed.DENY)
        self.assertEqual(settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
                         '"$CLAUDE_PROJECT_DIR/_meta/brain" gate check')

        raw = self.read_json(root / "brain.json")
        self.assertEqual((raw["name"], raw["prefix"], raw["description"]), ("homelab", "lab", "Running my lab"))
        self.assertNotIn("role", raw)
        self.assertEqual(config.load(root).role, "brain")
        self.assertEqual(raw["template"]["version"], template_version)
        self.assertEqual(raw["scripts"], {"python": "python3", "packages": "stdlib-only"})

        self.assertEqual(manifest.local_edits(root), [])
        self.assertIn("_meta/brain", manifest.read(root))
        self.assertEqual(self.git(root, "status", "--porcelain"), "")
        tracked = self.git(root, "ls-files").splitlines()
        for rel in ("brain.json", "CLAUDE.md", ".claude/settings.json", "_meta/MANIFEST.sha256"):
            self.assertIn(rel, tracked)
        for rel in tracked:
            self.assertFalse(rel.startswith("tests/") or rel.startswith("docs/superpowers/"), rel)
        shim = root / ".git" / "hooks" / "pre-commit"
        self.assertEqual(shim.read_text(encoding="utf-8"), hook.SHIM)
        self.assertTrue(os.access(shim, os.X_OK))
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return raw


class ConvertTest(InitCase):
    def test_plain_clone_gets_fresh_history(self):
        template, clone = self.plain_clone()
        before = self.git(clone, "rev-parse", "HEAD").strip()
        short = self.git(clone, "rev-parse", "--short", "HEAD").strip()
        version = f"{self.version_of(clone)}+{short}"

        r = self.done(clone)
        raw = self.assert_a_brain(clone, version)
        self.assertRegex(raw["template"]["version"], rf"^{re.escape(VERSION)}\+[0-9a-f]{{7,}}$")
        # the origin is a folder on this machine, so it goes to brain.local.json (ignored), not into the tracked
        # brain.json; the template is not published, so brain.json records no source
        self.assertIsNone(raw["template"]["source"])
        self.assertNotIn(str(self.tmp), (clone / "brain.json").read_text(encoding="utf-8"))
        self.assertEqual(self.read_json(clone / "brain.local.json"), {"template": {"source": str(template)}})
        self.assertEqual(config.effective_source(config.load(clone)), str(template))
        self.assertNotIn("brain.local.json", self.git(clone, "ls-files"))

        # a fresh history: one commit, the pinned message; the template's own commits are not in it
        self.assertEqual(self.commits(clone), [f"meta(brain): initialise from template v{version}"])
        self.assertEqual(len(self.git(clone, "rev-list", "--all").split()), 1)
        self.assertNotEqual(self.git(clone, "rev-parse", "HEAD").strip(), before)
        self.assertEqual(self.git(clone, "remote").strip(), "")  # the old remote went with the old repository

        # the old repository was moved, not deleted: it still holds the template's commits, and git reads it
        history = clone / HISTORY
        self.assertTrue(history.is_dir())
        self.assertEqual(self.git(clone, "--git-dir", str(history), "rev-parse", "HEAD").strip(), before)
        self.assertIn("template copy for tests", self.git(clone, "--git-dir", str(history), "log", "--format=%s"))
        self.assertNotIn(".brain", self.git(clone, "ls-files"))
        out = r.stdout.splitlines()
        self.assertIn(f"first commit {self.git(clone, 'rev-parse', '--short', 'HEAD').strip()}: "
                      f"meta(brain): initialise from template v{version}", out)
        self.assertTrue(any("template-history.git" in line for line in out), r.stdout)
        # the brain has no remote: say so, and how to give it one
        self.assertTrue(any("no remote" in line and "git remote add origin" in line for line in out), r.stdout)
        self.assertEqual(out[-1], f"open a session in {clone}")

    def test_use_this_template_keeps_history(self):
        used = self.used_template()
        first = self.git(used, "rev-parse", "HEAD").strip()
        version = f"{self.version_of(used)}+{self.git(used, 'rev-parse', '--short', 'HEAD').strip()}"

        r = self.done(used)
        self.assertNotIn("no remote", r.stdout)  # its own remote is kept
        raw = self.assert_a_brain(used, version)
        self.assertIsNone(raw["template"]["source"])  # the template is not published, so there is nothing to record
        self.assertFalse((used / HISTORY).exists())
        self.assertEqual(self.commits(used), [f"meta(brain): initialise from template v{version}", "Initial commit"])
        self.assertEqual(self.git(used, "rev-parse", "HEAD~1").strip(), first)
        self.assertEqual(self.git(used, "remote", "get-url", "origin").strip(),
                         "https://example.invalid/me/mybrain.git")
        # the template's tests are deleted in that commit, not left tracked
        self.assertEqual([p for p in self.git(used, "ls-files").splitlines() if p.startswith("tests/")], [])

    def test_use_this_template_records_the_canonical_source(self):
        used = self.used_template(source=CANONICAL)
        self.done(used)
        self.assertEqual(self.read_json(used / "brain.json")["template"]["source"], CANONICAL)

    def test_a_clone_whose_origin_is_the_canonical_source_is_a_plain_clone(self):
        _template, clone = self.plain_clone(source=CANONICAL)
        self.git(clone, "remote", "set-url", "origin", CANONICAL)
        self.done(clone)
        self.assertEqual(self.read_json(clone / "brain.json")["template"]["source"], CANONICAL)  # a URL stays tracked
        self.assertFalse((clone / "brain.local.json").exists())
        self.assertTrue((clone / HISTORY).is_dir())
        self.assertEqual(len(self.commits(clone)), 1)

    def test_a_local_origin_in_any_spelling_goes_to_brain_local_json(self):
        template = self.template_copy(source=CANONICAL)
        spellings = {
            "path": lambda clone: str(template),
            "file url": lambda clone: template.as_uri(),
            "relative path": lambda clone: os.path.relpath(str(template), str(clone)),
        }
        for label, spelling in spellings.items():
            with self.subTest(label):
                clone = self._new_dir("clone")
                self.git(self.tmp, "clone", "-q", str(template), str(clone))
                self.git(clone, "remote", "set-url", "origin", spelling(clone))
                self.done(clone)
                # the tracked value is the template's canonical source; this machine's folder is not tracked
                self.assertEqual(self.read_json(clone / "brain.json")["template"]["source"], CANONICAL)
                self.assertNotIn(str(self.tmp), (clone / "brain.json").read_text(encoding="utf-8"))
                self.assertEqual(self.read_json(clone / "brain.local.json"), {"template": {"source": str(template)}})

    def test_credentials_in_the_origin_are_never_recorded_or_printed(self):
        # The origin names the template, so init knows it, but its user and password are not the template's to record.
        secret = "pw" + "q" * 12  # put together here, so no source file holds one
        for label, userinfo in (("user and password", f"deploy:{secret}"), ("token as the user", secret)):
            with self.subTest(label):
                _template, clone = self.plain_clone(source=CANONICAL_GH)
                self.git(clone, "remote", "set-url", "origin",
                         f"https://{userinfo}@github.com/example/brain-template.git")
                dry = self.init(clone, "--dry-run")
                self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
                self.assertNotIn(secret, dry.stdout + dry.stderr)
                r = self.done(clone)
                self.assertNotIn(secret, r.stdout + r.stderr)
                self.assertEqual(self.read_json(clone / "brain.json")["template"]["source"], CANONICAL_GH)
                for rel in self.git(clone, "ls-files").splitlines():
                    self.assertNotIn(secret.encode(), (clone / rel).read_bytes(), rel)
                self.assertFalse((clone / "brain.local.json").exists())

    def test_a_recorded_origin_has_no_user_or_password(self):
        # Only a URL equal to the canonical source is recognised as the template, which records the canonical
        # source; this is the second line of defence for any other URL that gets this far.
        self.assertEqual(cmd_init._strip_userinfo("https://deploy:pw@example.invalid/o/r.git"),
                         "https://example.invalid/o/r.git")
        self.assertEqual(cmd_init._strip_userinfo("ssh://git@example.invalid:2222/o/r.git"),
                         "ssh://example.invalid:2222/o/r.git")
        for unchanged in ("https://example.invalid/o/r.git", "git@example.invalid:o/r.git", "/some/folder",
                          "https://example.invalid/o@r.git"):
            self.assertEqual(cmd_init._strip_userinfo(unchanged), unchanged)
        _template, clone = self.plain_clone()
        self.git(clone, "remote", "set-url", "origin", "https://deploy:" + "pw" + "q" * 12 + "@example.invalid/o/r.git")
        args = argparse.Namespace(name="homelab", prefix="lab", description="", python="python3",
                                  packages="stdlib-only", private=[], dry_run=True)
        plan = cmd_init._plan(args, clone, config.load(clone), cmd_init.MOVE)
        self.assertEqual(plan.raw["template"]["source"], "https://example.invalid/o/r.git")

    def test_no_repo_creates_one(self):
        folder = self.bare_folder()
        self.assertFalse((folder / ".git").exists())
        self.done(folder)
        raw = self.assert_a_brain(folder, self.version_of(folder))  # no repository: the VERSION file alone
        self.assertIsNone(raw["template"]["source"])
        self.assertTrue((folder / ".git").is_dir())
        self.assertFalse((folder / HISTORY).exists())
        self.assertEqual(self.commits(folder), [f"meta(brain): initialise from template v{self.version_of(folder)}"])

    def test_a_pushed_plain_clone_in_a_folder_with_a_space(self):
        # origin is the template folder, whose path holds a space; "every commit is on the remote" is true after a
        # fresh clone, so nothing stops the move
        _template, clone = self.plain_clone()
        self.assertIn(" ", str(clone))
        self.done(clone)
        self.assertTrue((clone / HISTORY / "HEAD").is_file())

    def test_private_patterns_python_and_packages(self):
        _template, clone = self.plain_clone()
        self.done(clone, "--private", "secret-project", "--private", r"host-\d+", "--python", ".venv/bin/python",
                  "--packages", "allowed")
        raw = self.read_json(clone / "brain.json")
        self.assertEqual(raw["scripts"], {"python": ".venv/bin/python", "packages": "allowed"})
        self.assertTrue(raw["privacy"]["private_file_expected"])
        private = (clone / ".brain-private").read_text(encoding="utf-8").splitlines()
        self.assertEqual([line for line in private if not line.startswith("#")], ["secret-project", r"host-\d+"])
        self.assertNotIn(".brain-private", self.git(clone, "ls-files"))
        self.assertEqual(self.git(clone, "status", "--porcelain"), "")
        self.assertEqual(config.load(clone).private_patterns, ["secret-project", r"host-\d+"])

    def test_the_new_brain_commits_through_its_own_guard(self):
        _template, clone = self.plain_clone()
        self.done(clone)
        (clone / "docs" / "note.md").write_text("a note\n", encoding="utf-8")
        self.git(clone, "add", "docs/note.md")
        self.git(clone, "commit", "-q", "-m", "docs: a note")
        self.assertEqual(len(self.git(clone, "rev-list", "HEAD").split()), 2)

    def test_runs_on_its_own_copy_whatever_the_current_folder_is(self):
        _template, clone = self.plain_clone()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        self.done(clone, cwd=elsewhere)
        self.assertTrue((clone / "brain.json").is_file())
        self.assertEqual(os.listdir(str(elsewhere)), [])

    def test_ignores_git_variables_that_name_another_repository(self):
        _template, clone = self.plain_clone()
        other = self.template_copy()
        before = self.git(other, "rev-parse", "HEAD")
        self.env["GIT_DIR"] = str(other / ".git")
        self.env["GIT_WORK_TREE"] = str(other)
        try:
            r = self.init(clone)
        finally:
            del self.env["GIT_DIR"], self.env["GIT_WORK_TREE"]
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.git(other, "rev-parse", "HEAD"), before)
        self.assertEqual(self.git(other, "status", "--porcelain"), "")
        self.assertEqual(len(self.commits(clone)), 1)


class DryRunTest(InitCase):
    def test_dry_run_writes_nothing(self):
        fixtures = {
            "plain clone": lambda: self.plain_clone()[1],
            "use this template": self.used_template,
            "no repo": self.bare_folder,
        }
        for label, make in fixtures.items():
            with self.subTest(label):
                root = make()
                before = self.snapshot(root)
                tree = sorted(os.listdir(str(root)))
                r = self.init(root, "--dry-run", "--private", "secret-project")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.snapshot(root), before)  # .git included
                self.assertEqual(sorted(os.listdir(str(root))), tree)
                self.assertFalse((root / ".brain-private").exists())
                lines = [line.strip() for line in r.stdout.splitlines()]
                self.assertIn("dry run: nothing is changed.", r.stdout.splitlines()[0])
                gone = "move {0} to .brain/template-only/{0}" if label == "no repo" else "remove {0}"
                for removed in ("tests", "docs", "brain.json", "CLAUDE.md", "README.md", ".gitignore",
                                ".claude/settings.json"):
                    self.assertIn(gone.format(removed), lines)
                self.assertTrue(any(line.startswith(gone.split("{")[0] + ".claude/skills/template-") for line in lines),
                                lines)
                for written in ("brain.json", "CLAUDE.md", "README.md", ".gitignore", ".claude/settings.json",
                                "docs/ROUTING.md", ".brain-private", "_meta/MANIFEST.sha256"):
                    self.assertIn(f"write {written}", lines)
                self.assertNotIn("write _meta/brain", lines)  # the shipped files are already in place
                self.assertTrue(any("initialise from template v" in line for line in lines), lines)
                self.assertTrue(any(line.startswith("rehearsed in a temporary copy") for line in lines), lines)
                self.assert_no_scratch_left()

    def test_dry_run_says_what_happens_to_the_history(self):
        _template, clone = self.plain_clone()
        plain = self.init(clone, "--dry-run").stdout
        self.assertIn(f"move .git to {HISTORY}", plain)
        self.assertIn("  write brain.local.json", plain.splitlines())  # the origin is a folder on this machine
        self.assertIn("keep the history", self.init(self.used_template(), "--dry-run").stdout)
        self.assertIn("run git init", self.init(self.bare_folder(), "--dry-run").stdout)

    def test_dry_run_refuses_what_a_run_refuses(self):
        _template, clone = self.plain_clone()
        (clone / "docs" / "scratch.md").write_text("x\n", encoding="utf-8")
        r = self.init(clone, "--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("uncommitted", r.stderr)


class RehearsalTest(InitCase):
    """The conversion is done once in a temporary copy first, so a step that would fail late (the guard refusing the
    first commit, git without an identity) is found while the folder is still untouched."""

    def test_a_private_term_in_the_filled_text_is_refused_with_nothing_changed(self):
        fixtures = {
            "plain clone": lambda: self.plain_clone()[1],
            "use this template": self.used_template,
            "no repo": self.bare_folder,
        }
        for label, make in fixtures.items():
            # "running my lab" is the description init writes into CLAUDE.md; "homelab" is the name in its heading
            for term in ("running my lab", "homelab"):
                with self.subTest(label, term=term):
                    root = make()
                    stderr = self.refused(root, "--private", term, message="rehearsed in a temporary copy")
                    self.assertIn("would fail, so nothing was changed", stderr)
                    self.assertIn("private-pattern", stderr)  # the guard's BLOCK line names the rule
                    self.assertNotIn(term, stderr.lower())  # and never the term
                    self.assertFalse((root / ".brain").exists())
                    self.assertFalse((root / ".brain-private").exists())
                    self.assertTrue((root / "tests").is_dir())
                    self.assertEqual(self.read_json(root / "brain.json")["name"], "brain-template")
                    if (root / ".git").is_dir():
                        self.assertEqual(self.git(root, "status", "--porcelain"), "")

    def test_a_missing_git_identity_is_refused_with_nothing_changed(self):
        _template, clone = self.plain_clone()
        for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
            self.env.pop(name, None)
        self.git(clone, "config", "--file", self.env["GIT_CONFIG_GLOBAL"], "user.useConfigOnly", "true")
        head = self.git(clone, "rev-parse", "HEAD")
        stderr = self.refused(clone, message="rehearsed in a temporary copy")
        self.assertIn("would fail, so nothing was changed", stderr)
        self.assertRegex(stderr, r"(?i)identity|who you are|auto-detection")
        self.assertFalse((clone / ".brain").exists())
        self.assertEqual(self.git(clone, "rev-parse", "HEAD"), head)

    def test_dry_run_reports_the_rehearsal_failing_too(self):
        _template, clone = self.plain_clone()
        stderr = self.refused(clone, "--dry-run", "--private", "running my lab", message="rehearsed in a temporary")
        self.assertIn("private-pattern", stderr)

    def test_the_rehearsal_leaves_no_scratch_folder_and_the_real_run_is_unaffected(self):
        _template, clone = self.plain_clone()
        self.assertEqual(self.init(clone, "--dry-run").returncode, 0)
        self.assert_no_scratch_left()
        self.done(clone)
        self.assertEqual(len(self.commits(clone)), 1)

    def test_a_failure_the_rehearsal_did_not_foresee_says_where_the_old_history_is(self):
        # Only if something changes between the rehearsal and the real run. Skip the rehearsal to simulate that.
        _template, clone = self.plain_clone()
        parser = argparse.ArgumentParser()
        cmd_init.add_arguments(parser)
        args = parser.parse_args(["--name", "homelab", "--prefix", "lab", "--description", "Running my lab",
                                  "--private", "running my lab"])
        err = io.StringIO()
        with mock.patch.object(cmd_init.paths, "harness_root", return_value=clone), \
                mock.patch.object(cmd_init, "_rehearse", return_value=None), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cmd_init.run(args)
        self.assertEqual(code, 1, err.getvalue())
        self.assertIn("first commit failed", err.getvalue())
        self.assertIn(HISTORY, err.getvalue())
        self.assertTrue((clone / HISTORY / "HEAD").is_file())
        self.assertTrue((clone / "brain.json").is_file())
        self.assertEqual(self.git(clone, "rev-list", "--all").strip(), "")  # a repository with no commit yet


    def test_a_failure_before_the_move_does_not_claim_the_history_was_moved(self):
        _template, clone = self.plain_clone()
        parser = argparse.ArgumentParser()
        cmd_init.add_arguments(parser)
        args = parser.parse_args(["--name", "homelab", "--prefix", "lab"])
        err = io.StringIO()
        with mock.patch.object(cmd_init.paths, "harness_root", return_value=clone), \
                mock.patch.object(cmd_init, "_rehearse", return_value=None), \
                mock.patch.object(cmd_init.os, "rename", side_effect=OSError(18, "Invalid cross-device link")), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cmd_init.run(args)
        self.assertEqual(code, 1, err.getvalue())
        self.assertIn("stopped before the first commit", err.getvalue())
        self.assertNotIn("template-history.git", err.getvalue())
        self.assertNotIn("history is in", err.getvalue())
        self.assertTrue((clone / ".git").is_dir())  # the repository was never moved
        self.assertFalse((clone / HISTORY).exists())


class RefusalTest(InitCase):
    def test_refusals(self):
        def with_local():
            copy = self.template_copy()
            (copy / "local").mkdir()
            return copy

        def modified():
            _t, clone = self.plain_clone()
            with open(str(clone / "_meta" / "CHANGELOG.md"), "a", encoding="utf-8") as handle:
                handle.write("- an edit\n")
            return clone

        def untracked():
            _t, clone = self.plain_clone()
            (clone / "docs" / "scratch.md").write_text("x\n", encoding="utf-8")
            return clone

        def staged():
            _t, clone = self.plain_clone()
            (clone / "docs" / "staged.md").write_text("x\n", encoding="utf-8")
            self.git(clone, "add", "docs/staged.md")
            return clone

        def dirty_kept_history():
            used = self.used_template()
            (used / "docs" / "scratch.md").write_text("x\n", encoding="utf-8")
            return used

        def unpushed():
            _t, clone = self.plain_clone()
            (clone / "_meta" / "CHANGELOG.md").write_text("# Changelog\n\n- mine\n", encoding="utf-8")
            self.git(clone, "add", "-A")
            self.git(clone, "commit", "-q", "-m", "a local commit")
            return clone

        def unpushed_branch():
            _t, clone = self.plain_clone()
            self.git(clone, "switch", "-q", "-c", "side")
            (clone / "_meta" / "CHANGELOG.md").write_text("# Changelog\n\n- side\n", encoding="utf-8")
            self.git(clone, "add", "-A")
            self.git(clone, "commit", "-q", "-m", "on a side branch")
            self.git(clone, "switch", "-q", "main")
            return clone

        def stashed():
            _t, clone = self.plain_clone()
            (clone / "_meta" / "CHANGELOG.md").write_text("# Changelog\n\n- stashed\n", encoding="utf-8")
            self.git(clone, "stash", "-q")
            return clone

        def history_in_the_way():
            _t, clone = self.plain_clone()
            (clone / HISTORY).mkdir(parents=True)
            return clone

        def brain_folder():
            return self.make_brain()

        def linked_worktree():
            template = self.template_copy()
            worktree = self.tmp / "linked wt"
            self.git(template, "worktree", "add", "-q", str(worktree), "-b", "side")
            return worktree

        def not_a_repository():
            folder = self.bare_folder()
            (folder / ".git").mkdir()
            return folder

        def no_commit():
            folder = self.bare_folder()
            self.git(folder, "init", "-q")
            return folder

        def foreign_hook():
            used = self.used_template()
            target = used / ".git" / "hooks" / "pre-commit"
            target.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
            return used

        def hooks_path_in_the_repo():
            used = self.used_template()
            self.git(used, "config", "core.hooksPath", "elsewhere")
            return used

        def hooks_path_globally():
            _t, clone = self.plain_clone()
            self.git(clone, "config", "--file", self.env["GIT_CONFIG_GLOBAL"], "core.hooksPath", "elsewhere")
            return clone

        cases = [
            ("local/ exists", with_local, "local/"),
            ("modified file", modified, "uncommitted"),
            ("untracked file", untracked, "uncommitted"),
            ("staged file", staged, "uncommitted"),
            ("dirty tree, history kept", dirty_kept_history, "uncommitted"),
            ("unpushed commit on a plain clone", unpushed, "origin does not"),
            ("unpushed commit on another branch", unpushed_branch, "origin does not"),
            ("stash on a plain clone", stashed, "stash"),
            ("history folder already there", history_in_the_way, "template-history.git"),
            ("role not template", brain_folder, "copy of the template"),
            ("linked worktree", linked_worktree, "worktree"),
            ("a .git that is not a repository", not_a_repository, "not a repository"),
            ("a repository with no commit", no_commit, "no commit"),
            ("a foreign pre-commit hook", foreign_hook, "pre-commit"),
            ("core.hooksPath in the repository", hooks_path_in_the_repo, "core.hooksPath"),
            ("core.hooksPath in the global config", hooks_path_globally, "core.hooksPath"),
        ]
        for label, make, message in cases:
            with self.subTest(label):
                root = make()
                self.refused(root, message=message)
                if root.joinpath(".git").is_dir() and "history folder" not in label:
                    self.assertFalse((root / HISTORY).exists())  # nothing was moved

    def test_an_unpushed_commit_on_a_plain_clone_leaves_everything_in_place(self):
        _t, clone = self.plain_clone()
        (clone / "_meta" / "CHANGELOG.md").write_text("# Changelog\n\n- mine\n", encoding="utf-8")
        self.git(clone, "add", "-A")
        self.git(clone, "commit", "-q", "-m", "a local commit")
        head = self.git(clone, "rev-parse", "HEAD")
        self.refused(clone)
        self.assertTrue((clone / ".git").is_dir())
        self.assertFalse((clone / ".brain").exists())
        self.assertTrue((clone / "tests").is_dir())
        self.assertEqual(self.git(clone, "rev-parse", "HEAD"), head)

    def test_a_commit_known_only_to_another_remote_is_not_on_the_origin(self):
        # "every commit is on that remote": the origin, not any remote-tracking branch at all
        _t, clone = self.plain_clone()
        (clone / "_meta" / "CHANGELOG.md").write_text("# Changelog\n\n- mine\n", encoding="utf-8")
        self.git(clone, "add", "-A")
        self.git(clone, "commit", "-q", "-m", "a local commit")
        self.git(clone, "remote", "add", "other", "https://example.invalid/me/other.git")
        self.git(clone, "update-ref", "refs/remotes/other/main", "HEAD")
        self.refused(clone, message="origin does not")
        self.assertTrue((clone / "tests").is_dir())

    def test_unpushed_commits_are_fine_when_no_history_is_replaced(self):
        # "Use this template": the person's history is kept, so nothing can be lost, pushed or not.
        used = self.used_template()
        self.assertEqual(self.git(used, "rev-list", "--count", "--branches", "--not", "--remotes").strip(), "1")
        self.done(used)

    def test_refuses_bad_arguments(self):
        _t, clone = self.plain_clone()
        for prefix in ("brain", "template", "A", "x", "1abc", "a-b", "a" * 17):
            with self.subTest(prefix=prefix):
                self.refused(clone, prefix=prefix, message="prefix")
        self.refused(clone, name="two\nlines", message="name")
        self.refused(clone, name="  ", message="name")
        self.refused(clone, description="one\r\ntwo", message="description")
        self.refused(clone, "--private", "(", message="--private")
        self.refused(clone, "--private", "# comment", message="--private")
        self.refused(clone, "--private", "  ", message="--private")

    def test_refuses_a_link_among_the_paths_init_removes_or_writes(self):
        # A link on the way to something init removes or writes could send that to another place, and a rehearsal
        # copy that keeps the link would do it in the real folder, even on a dry run.
        def link_inside(name, absolute):
            def arrange(folder):
                shutil.move(str(folder / name), str(folder / f"keep-{name.lstrip('.')}"))
                target = folder / f"keep-{name.lstrip('.')}"
                (folder / name).symlink_to(target if absolute else target.name)
            return arrange

        def link_outside(folder):
            outside = self._new_dir("outside")
            shutil.move(str(folder / ".claude"), str(outside / ".claude"))
            (folder / ".claude").symlink_to(outside / ".claude")
            return outside

        def link_to_a_file(folder):
            (folder / "CLAUDE.md").unlink()
            (folder / "CLAUDE.md").symlink_to("README.md")

        def link_above_a_new_file(folder):
            (folder / "keep-scripts").mkdir()
            (folder / "scripts").symlink_to("keep-scripts")  # scripts/README.md is written

        cases = [
            ("absolute link into the folder", link_inside(".claude", True), ".claude"),
            ("relative link into the folder", link_inside(".claude", False), ".claude"),
            ("link outside the folder", link_outside, ".claude"),
            ("docs is a link", link_inside("docs", True), "docs"),
            ("CLAUDE.md is a link", link_to_a_file, "CLAUDE.md"),
            ("scripts is a link", link_above_a_new_file, "scripts"),
        ]
        for label, arrange, name in cases:
            for flags in ([], ["--dry-run"]):
                with self.subTest(label, flags=flags):
                    folder = self.bare_folder()
                    outside = arrange(folder)  # a folder outside the one being converted, when there is one
                    before = self.snapshot(outside) if outside is not None else None
                    stderr = self.refused(folder, *flags, message=name)
                    self.assertIn("link", stderr)
                    if outside is not None:
                        self.assertEqual(self.snapshot(outside), before)

    def test_refuses_a_hooks_folder_or_hook_that_is_a_link(self):
        # `.git/hooks` is written by the guard's installer, in the rehearsal copy of a kept repository and in the real
        # one; through a link it would write outside the folder, even on a dry run.
        def folder_link(used):
            outside = self._new_dir("hooks")
            shutil.rmtree(str(used / ".git" / "hooks"))
            (used / ".git" / "hooks").symlink_to(outside)  # absolute
            return outside

        def hook_link(used):
            outside = self._new_dir("hooks")
            (outside / "mine").write_text("#!/bin/sh\n", encoding="utf-8")
            (used / ".git" / "hooks" / "pre-commit").symlink_to(outside / "mine")
            return outside

        for label, arrange, name in (("hooks folder", folder_link, ".git/hooks"),
                                     ("pre-commit hook", hook_link, ".git/hooks/pre-commit")):
            for flags in ([], ["--dry-run"]):
                with self.subTest(label, flags=flags):
                    used = self.used_template()
                    outside = arrange(used)
                    before = self.snapshot(outside)
                    stderr = self.refused(used, *flags, message=name)
                    self.assertIn("link", stderr)
                    self.assertEqual(self.snapshot(outside), before)  # nothing was written through the link

    def test_refuses_an_absolute_link_that_points_back_into_the_folder(self):
        # Not on a removed or written path, but a rehearsal copy that keeps it would point into the real folder.
        for flags in ([], ["--dry-run"]):
            with self.subTest(flags=flags):
                folder = self.bare_folder()
                (folder / "alias").symlink_to(folder / "_meta")
                self.refused(folder, *flags, message="alias")

    def test_a_relative_link_inside_the_folder_is_fine(self):
        folder = self.bare_folder()
        (folder / "alias").symlink_to("_meta")
        self.done(folder)
        self.assertTrue((folder / "alias").is_symlink())
        self.assertEqual(self.git(folder, "status", "--porcelain"), "")

    def test_a_hooks_path_only_the_real_location_sees_is_rolled_back(self):
        # `includeIf "gitdir:..."` matches the repository at its real place: not the scratch folder the up-front
        # check asks from, nor the rehearsal copy. The fresh repository shows it, and the move is undone.
        for label, make in (("plain clone", lambda: self.plain_clone()[1]), ("no repo", self.bare_folder)):
            with self.subTest(label):
                root = make()
                extra = self._new_dir("config") / "hooks.gitconfig"
                extra.write_text("[core]\n\thooksPath = elsewhere\n", encoding="utf-8")
                self.git(root, "config", "--file", self.env["GIT_CONFIG_GLOBAL"],
                         f"includeIf.gitdir:{root}/.git.path", str(extra))
                self.refused(root, message="core.hooksPath")
                self.assertFalse((root / ".brain").exists())
                self.assertEqual((root / ".git").is_dir(), label == "plain clone")  # the old repository is back

    def test_missing_arguments_are_a_usage_error(self):
        _t, clone = self.plain_clone()
        before = self.snapshot(clone)
        for args in (["init"], ["init", "--name", "x"], ["init", "--prefix", "lab"], ["init", "--name", "x",
                                                                                     "--prefix", "lab", "--packages",
                                                                                     "maybe"]):
            with self.subTest(args=args):
                r = self.run_brain(clone, *args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("usage: brain", r.stderr)
        self.assertEqual(self.snapshot(clone), before)

    def test_help_lists_the_options(self):
        r = self.run_brain(TEMPLATE_ROOT, "init", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for option in ("--name", "--prefix", "--description", "--python", "--packages", "--private", "--dry-run"):
            self.assertIn(option, r.stdout)


class IsPlainCloneTest(InitCase):
    def test_origin_is_the_template_checkout(self):
        _t, clone = self.plain_clone()
        self.assertTrue(cmd_init.is_plain_clone(clone, config.load(clone)))

    def test_origin_as_a_file_url_and_a_trailing_slash(self):
        template, clone = self.plain_clone()
        for url in (template.as_uri(), str(template) + "/"):
            with self.subTest(url=url):
                self.git(clone, "remote", "set-url", "origin", url)
                self.assertTrue(cmd_init.is_plain_clone(clone, config.load(clone)))

    def test_origin_equals_the_canonical_source(self):
        used = self.used_template(source=CANONICAL)
        cfg = config.load(used)
        self.assertEqual(cfg.template_source, CANONICAL)
        self.assertFalse(cmd_init.is_plain_clone(used, cfg))  # origin is the person's own repository
        for url in (CANONICAL, CANONICAL[:-4], CANONICAL + "/", CANONICAL[:-4] + "/"):
            with self.subTest(url=url):
                self.git(used, "remote", "set-url", "origin", url)
                self.assertTrue(cmd_init.is_plain_clone(used, cfg))

    def test_origin_equals_the_canonical_source_in_any_spelling(self):
        # The same repository as https, ssh or scp-style, with a user, a port, another case, a trailing .git or /
        spellings = [
            "https://github.com/example/brain-template.git",
            "https://github.com/example/brain-template",
            "https://github.com/example/brain-template/",
            "https://someone@github.com/example/brain-template.git",
            "https://github.com:443/example/brain-template.git",
            "HTTPS://GitHub.com/Example/Brain-Template.git",
            "https://github.com/example/brain-template.GIT",
            "git@github.com:example/brain-template.git",
            "git@github.com:example/brain-template",
            "github.com:example/brain-template.git",
            "ssh://git@github.com/example/brain-template.git",
            "ssh://git@github.com:22/example/brain-template.git",
            "git://github.com/example/brain-template.git",
        ]
        for canonical in (CANONICAL_GH, "git@github.com:example/brain-template.git"):
            used = self.used_template(source=canonical)
            cfg = config.load(used)
            for url in spellings:
                with self.subTest(canonical=canonical, origin=url):
                    self.git(used, "remote", "set-url", "origin", url)
                    self.assertTrue(cmd_init.is_plain_clone(used, cfg))

    def test_origin_that_names_another_repository_is_not_the_canonical_source(self):
        used = self.used_template(source=CANONICAL_GH)
        cfg = config.load(used)
        for url in ("https://github.com/example/other-template.git",
                    "https://github.com/other/brain-template.git",
                    "https://gitlab.com/example/brain-template.git",
                    "git@github.com:other/brain-template.git",
                    "https://github.com/example/brain-template.git.old",
                    "https://github.com/example",
                    "https://github.com/",
                    "git@github.com:",
                    "https://github.com/example/brain-template-fork"):
            with self.subTest(origin=url):
                self.git(used, "remote", "set-url", "origin", url)
                self.assertFalse(cmd_init.is_plain_clone(used, cfg))

    def test_origin_that_is_not_the_template(self):
        used = self.used_template()
        cfg = config.load(used)
        self.assertFalse(cmd_init.is_plain_clone(used, cfg))  # a URL, and the template has no canonical source
        self.git(used, "remote", "set-url", "origin", "git@example.invalid:me/mybrain.git")
        self.assertFalse(cmd_init.is_plain_clone(used, cfg))
        brain = self.make_brain()  # a local path whose brain.json is a brain, not the template
        self.git(used, "remote", "set-url", "origin", str(brain))
        self.assertFalse(cmd_init.is_plain_clone(used, cfg))
        folder = self._new_dir("plain folder")  # a local path with no brain.json at all
        self.git(used, "remote", "set-url", "origin", str(folder))
        self.assertFalse(cmd_init.is_plain_clone(used, cfg))
        self.git(used, "remote", "set-url", "origin", str(self.tmp / "gone"))
        self.assertFalse(cmd_init.is_plain_clone(used, cfg))

    def test_no_origin_and_no_repo(self):
        used = self.used_template()
        self.git(used, "remote", "remove", "origin")
        self.assertFalse(cmd_init.is_plain_clone(used, config.load(used)))
        folder = self.bare_folder()
        self.assertFalse(cmd_init.is_plain_clone(folder, config.load(folder)))

    def test_only_origin_counts(self):
        used = self.used_template()
        template, _clone = self.plain_clone()
        self.git(used, "remote", "add", "upstream", str(template))
        self.assertFalse(cmd_init.is_plain_clone(used, config.load(used)))


class ShapeTest(InitCase):
    def test_template_only_paths(self):
        self.assertEqual(cmd_init.TEMPLATE_ONLY, [".claude/skills/template-*", "tests", "docs", "CLAUDE.md",
                                                  "README.md", ".gitignore", ".claude/settings.json", "brain.json"])

    def test_the_command_is_registered(self):
        from brainlib import cli

        self.assertEqual(cli.COMMANDS["init"][0], "cmd_init")
        self.assertEqual(list(cli.COMMANDS), sorted(cli.COMMANDS))

    def test_the_version_pattern_matches_the_pinned_message(self):
        _t, clone = self.plain_clone()
        self.done(clone)
        self.assertRegex(self.commits(clone)[0],
                         rf"^meta\(brain\): initialise from template v{re.escape(VERSION)}\+[0-9a-f]{{7,}}$")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{7,}", self.git(clone, "rev-parse", "--short", "HEAD").strip()))


if __name__ == "__main__":
    unittest.main()
