from __future__ import annotations

import json
import os
import shutil
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config, doctor, gitutil
from brainlib.report import BLOCK, OK, WARN, Finding

SECRET = "s3cr3t" + "-value-" + "9f8e7d"  # planted at runtime; no finding may ever show it


class DoctorCase(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        # In-process git calls get the isolated environment too: the person's own git config never reaches a test.
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- builders -----------------------------------------------------------------------------

    def clone(self, brain: Path) -> Path:
        """A copy of a made brain (its .git and hook included), so each sub-test starts from a healthy one."""
        dest = self._new_dir("clone")
        shutil.copytree(str(brain), str(dest), symlinks=True, dirs_exist_ok=True)
        return dest

    def template_of(self, brain: Path) -> Path:
        local = json.loads((brain / "brain.local.json").read_text(encoding="utf-8"))
        return Path(local["template"]["source"])

    def edit_json(self, path: Path, change) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def edit_brain_json(self, brain: Path, change) -> None:
        self.edit_json(brain / "brain.json", change)

    def write(self, path: Path, text: str, mode: int = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if mode is not None:
            os.chmod(str(path), mode)
        return path

    def bare_remote(self) -> Path:
        remote = self._new_dir("remote")
        self.git(remote, "init", "-q", "--bare")
        return remote

    def nested_repo(self, brain: Path, name: str = "projects/app") -> Path:
        repo = brain / name
        repo.mkdir(parents=True)
        self.git(repo, "init", "-q")
        self.write(repo / "main.txt", "work\n")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "first")
        return repo

    # -- reading output -------------------------------------------------------------------------

    def doctor(self, root, *args):
        return self.run_brain(root, "doctor", *args)

    @staticmethod
    def found(result, severity=None, subject=None, text=None):
        """The (severity, subject, message) of each output line that matches; None matches anything."""
        matches = []
        for line in result.stdout.splitlines():
            head, _sep, rest = line.partition(" ")
            subj, sep, message = rest.lstrip().partition(": ")
            if not sep or line.startswith("doctor:"):
                continue
            if severity is not None and head != severity:
                continue
            if subject is not None and subj != subject:
                continue
            if text is not None and text not in message:
                continue
            matches.append((head, subj, message))
        return matches

    def in_process(self, root: Path, quick: bool = False):
        return doctor.checks(root, config.load(root), quick)

    @staticmethod
    def has(findings, severity, subject, text=None):
        return [f for f in findings
                if f.severity == severity and f.subject == subject and (text is None or text in f.message)]


class FreshBrainTest(DoctorCase):
    def test_fresh_brain_full_doctor_has_no_block(self):
        brain = self.make_brain()
        r = self.doctor(brain)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.found(r, BLOCK), [])
        # Python 3.12+ `unittest discover` exits 5 on an empty folder; that is "no tests yet", not a failure.
        self.assertTrue(self.found(r, OK, "script tests", "no script tests yet"), r.stdout)
        self.assertTrue(self.found(r, WARN, "git", "no remote"), r.stdout)  # a new brain has nowhere to push
        self.assertRegex(r.stdout.splitlines()[-1], r"^doctor: 0 block, \d+ warn$")

    def test_summary_counts_the_lines_it_follows(self):
        brain = self.make_brain()
        self.write(brain / "docs" / "stray.md", "x\n")  # one more WARN: uncommitted work
        r = self.doctor(brain)
        blocks = len(self.found(r, BLOCK))
        warns = len(self.found(r, WARN))
        self.assertEqual(r.stdout.splitlines()[-1], f"doctor: {blocks} block, {warns} warn")
        self.assertGreaterEqual(warns, 2)

    def test_usage_error_is_exit_2(self):
        r = self.doctor(self.fake_brain(), "--no-such-flag")
        self.assertEqual(r.returncode, 2)

    def test_help_names_quick(self):
        r = self.doctor(self.fake_brain(), "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--quick", r.stdout)

    def test_runs_from_any_cwd(self):
        brain = self.make_brain()
        r = self.run_brain(brain, "doctor", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class BlockTest(DoctorCase):
    def test_each_block(self):
        base = self.make_brain()

        def hooks_dir(b):
            return b / ".git" / "hooks"

        def set_python(b, value):
            self.edit_brain_json(b, lambda d: d.setdefault("scripts", {}).update(python=value))

        def bad_skill(b):
            self.make_skill(b, "lab-bad", "", "Body.")

        def gate_names_missing_skill(b):
            self.edit_brain_json(b, lambda d: d.update(
                gates=[{"path": "docs/x/**", "skills": ["lab-missing"], "why": "a test rule"}]))

        def broken_router(b):
            self.write(b / ".claude" / "skills" / "lab-router" / "rules.json", '{"rules": "not a list"}\n')

        def bad_practice(b):
            self.write(b / "docs" / "practices" / "no-fields.md", "no frontmatter at all\n")

        def failing_script_test(b):
            self.write(b / "scripts" / "tests" / "test_fail.py",
                       "import unittest\n\n\nclass T(unittest.TestCase):\n"
                       "    def test_fail(self):\n        self.fail('x')\n")

        def hooks_path(b):
            self.git(b, "config", "core.hooksPath", str(b / "other-hooks"))

        cases = [
            ("brain.json is not JSON", lambda b: (b / "brain.json").write_text("{ nope", encoding="utf-8"),
             "brain.json", "not valid JSON"),
            ("brain.json has a bad role", lambda b: self.edit_brain_json(b, lambda d: d.update(role="x")),
             "brain.json", "role"),
            ("prefix not set", lambda b: self.edit_brain_json(b, lambda d: d.pop("prefix")),
             "brain.json", "prefix is not set"),
            ("reserved prefix", lambda b: self.edit_brain_json(b, lambda d: d.update(prefix="brain")),
             "brain.json", "reserved"),
            ("scripts.python missing", lambda b: set_python(b, "no-such-python-xyz"),
             "tools", "no-such-python-xyz"),
            ("template-* skill in a brain",
             lambda b: self.make_skill(b, "template-extra", "Does NOT matter.", "Body."),
             "template files", "template-extra"),
            ("tests/.brain-template in a brain", lambda b: self.write(b / "tests" / ".brain-template", ""),
             "template files", "tests/.brain-template"),
            ("hook missing", lambda b: (hooks_dir(b) / "pre-commit").unlink(), "hook", "pre-commit"),
            ("core.hooksPath set", hooks_path, "hook", "core.hooksPath"),
            ("a hook that does not run the guard",
             lambda b: self.write(hooks_dir(b) / "pre-commit", "#!/bin/sh\nexit 0\n", 0o755),
             "hook", "does not run"),
            ("the hook is not executable", lambda b: os.chmod(str(hooks_dir(b) / "pre-commit"), 0o644),
             "hook", "not executable"),
            ("no git repository", lambda b: shutil.rmtree(str(b / ".git")), "hook", "not a git repository"),
            ("a skill with no description", bad_skill, "lint", "lab-bad"),
            ("a gate rule naming a missing skill", gate_names_missing_skill, "lint", "lab-missing"),
            ("a router's rules.json that is broken", broken_router, "lint", "lab-router"),
            ("a practice with no frontmatter", bad_practice, "docs/practices/no-fields.md", "frontmatter"),
            ("a failing script test", failing_script_test, "script tests", "failed"),
        ]
        for label, mutate, subject, text in cases:
            with self.subTest(label):
                brain = self.clone(base)
                mutate(brain)
                r = self.doctor(brain)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertTrue(self.found(r, BLOCK, subject, text), r.stdout)
                self.assertRegex(r.stdout.splitlines()[-1], r"^doctor: [1-9]\d* block, \d+ warn$")

    def test_a_tool_that_is_missing_blocks(self):
        brain = self.make_brain()
        cfg = config.load(brain)
        real = shutil.which
        for tool in ("git", "python3"):
            with self.subTest(tool):
                with mock.patch("brainlib.doctor.shutil.which",
                                side_effect=lambda name, tool=tool: None if name == tool else real(name)):
                    found = doctor.checks(brain, cfg, True)
                self.assertTrue(self.has(found, BLOCK, "tools", tool), found)

    def test_copy_of_the_template_never_set_up_blocks(self):
        template = self.copy_template(with_local=False)
        r = self.doctor(template)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        lines = self.found(r, BLOCK, "template", "never set up")
        self.assertTrue(lines, r.stdout)
        self.assertIn("brain-setup", lines[0][2])
        self.assertIn("create local/", lines[0][2])

    def test_a_broken_brain_json_still_reports_the_tools(self):
        brain = self.fake_brain()
        (brain / "brain.json").write_text("[]", encoding="utf-8")
        r = self.doctor(brain)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(self.found(r, BLOCK, "brain.json", "JSON object"), r.stdout)
        self.assertTrue(self.found(r, OK, "tools"), r.stdout)

    def test_a_check_that_crashes_blocks_instead_of_passing(self):
        brain = self.make_brain()
        with mock.patch("brainlib.doctor.lint.all_findings", side_effect=RuntimeError("boom " + SECRET)):
            found = self.in_process(brain, quick=True)
        self.assertTrue(self.has(found, BLOCK, "lint", "could not run"), found)
        self.assertNotIn(SECRET, " ".join(f.message for f in found))


class HookTest(DoctorCase):
    def test_a_hook_the_person_kept_counts_when_it_calls_the_guard(self):
        brain = self.make_brain()
        kept = "#!/bin/sh\n# my own checks first\nmake lint || exit 1\n" \
               'exec "$(git rev-parse --show-toplevel)/_meta/brain" hook pre-commit\n'
        self.write(brain / ".git" / "hooks" / "pre-commit", kept, 0o755)
        found = self.in_process(brain, quick=True)
        self.assertTrue(self.has(found, OK, "hook"), found)
        self.assertFalse([f for f in found if f.severity == BLOCK], found)

    def test_the_shim_counts(self):
        brain = self.make_brain()
        found = self.in_process(brain, quick=True)
        self.assertTrue(self.has(found, OK, "hook", "installed"), found)

    def test_hook_in_a_linked_worktree_is_found_in_the_common_dir(self):
        brain = self.make_brain()
        tree = self.tmp / "linked tree"
        self.git(brain, "worktree", "add", "-q", "--detach", str(tree))
        found = self.in_process(tree, quick=True)
        self.assertTrue(self.has(found, OK, "hook"), found)


class TemplateTest(DoctorCase):
    def test_template_checkout_is_ok(self):
        template = self.copy_template(with_local=True)
        r = self.doctor(template)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.found(r, OK, "template", "this is the template"), r.stdout)
        self.assertEqual(self.found(r, None, "manifest"), [], r.stdout)  # the template has no manifest
        self.assertEqual(self.found(r, None, "source"), [], r.stdout)
        self.assertEqual(self.found(r, None, "template files"), [], r.stdout)  # its own skills are not strays
        self.assertEqual(self.found(r, BLOCK), [])


class WarnTest(DoctorCase):
    def test_each_warn(self):
        base = self.make_brain()
        remote = self.bare_remote()

        def edit_settings(b, change):
            self.edit_json(b / ".claude" / "settings.json", change)

        def lose_deny(d):
            d["permissions"]["deny"] = []

        def lose_hook(event):
            def change(d):
                d["hooks"][event] = []
            return change

        def invalid_settings(b):
            (b / ".claude" / "settings.json").write_text("{ nope", encoding="utf-8")

        def stale_practice(b):
            old = (date.today() - timedelta(days=400)).isoformat()
            self.write(b / "docs" / "practices" / "old-fact.md",
                       f"---\nid: old-fact\ntags: [x]\ndurability: durable\nevidence: researched\n"
                       f"verified: {old}\nsource: somewhere\nreviewed-against: []\n---\nA fact.\n")

        def with_remote(b):
            self.git(b, "remote", "add", "origin", str(remote))
            self.git(b, "push", "-q", "-u", "origin", "HEAD")

        def unpushed(b):
            with_remote(b)
            self.git(b, "commit", "-q", "--allow-empty", "-m", "local only")

        def nested_without_remote(b):
            self.nested_repo(b)

        def nested_unpushed(b):
            repo = self.nested_repo(b)
            self.git(repo, "remote", "add", "origin", str(self.bare_remote()))
            self.git(repo, "push", "-q", "-u", "origin", "HEAD")
            self.write(repo / "more.txt", "more\n")
            self.git(repo, "add", "-A")
            self.git(repo, "commit", "-q", "-m", "second")

        def big_tracked_file(b):
            self.write(b / "docs" / "big.md", "x" * 200 * 1024)
            self.git(b, "add", "docs/big.md")
            self.edit_brain_json(b, lambda d: d["privacy"].update(max_file_kb=100))

        def private_expected(b):
            self.edit_brain_json(b, lambda d: d["privacy"].update(private_file_expected=True))

        def docs_folder(b):
            self.write(b / "docs" / "guides" / "intro.md", "# Intro\n")

        def keys_missing(b):
            self.write(b / ".env.example", "# names only\nLAB_TOKEN=\nLAB_HOST=\n")
            self.write(b / ".env", f"LAB_HOST={SECRET}\n", 0o600)

        def gap_skill(b):
            self.make_skill(b, "lab-gap", "Does something useful.", "Body.")

        cases = [
            ("a template file was edited",
             lambda b: self.write(b / "_meta" / "VERSION", "9.9.9\n"),
             "manifest", "_meta/VERSION"),
            ("the manifest is missing", lambda b: (b / "_meta" / "MANIFEST.sha256").unlink(),
             "manifest", "MANIFEST.sha256"),
            ("settings.json is missing", lambda b: (b / ".claude" / "settings.json").unlink(),
             "settings", "settings.json"),
            ("settings.json is not JSON", invalid_settings, "settings", "not valid JSON"),
            ("settings no longer denies .env", lambda b: edit_settings(b, lose_deny), "settings", "Read(./.env)"),
            ("settings lost the gate check hook", lambda b: edit_settings(b, lose_hook("PreToolUse")),
             "settings", "gate check"),
            ("settings lost the gate record hook", lambda b: edit_settings(b, lose_hook("PostToolUse")),
             "settings", "gate record"),
            (".env is group readable", lambda b: self.write(b / ".env", "A=\n", 0o644), ".env", "644"),
            ("keys missing from .env", keys_missing, ".env", "LAB_TOKEN"),
            ("a skill with a gap", gap_skill, "lint", "gap"),
            ("a stale practice", stale_practice, "docs/practices/old-fact.md", "re-verify"),
            ("no remote", lambda b: None, "git", "no remote"),
            ("uncommitted work", lambda b: self.write(b / "docs" / "note.md", "a note\n"), "git", "uncommitted"),
            ("unpushed commits", unpushed, "git", "not pushed"),
            ("a nested repo with no remote", nested_without_remote, "projects/app", "no remote"),
            ("a nested repo with unpushed commits", nested_unpushed, "projects/app", "not pushed"),
            ("a docs folder docs/README.md never mentions", docs_folder, "docs", "guides"),
            ("a tracked file over max_file_kb", big_tracked_file, "files", "docs/big.md"),
            ("private_file_expected without .brain-private", private_expected, "privacy", ".brain-private"),
        ]
        for label, mutate, subject, text in cases:
            with self.subTest(label):
                brain = self.clone(base)
                mutate(brain)
                r = self.doctor(brain)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)  # a WARN never fails the run
                self.assertTrue(self.found(r, WARN, subject, text), r.stdout)

    def test_the_same_brain_is_quiet_when_nothing_is_wrong(self):
        brain = self.make_brain()
        remote = self.bare_remote()
        self.git(brain, "remote", "add", "origin", str(remote))
        self.git(brain, "push", "-q", "-u", "origin", "HEAD")
        self.write(brain / ".env.example", "LAB_TOKEN=\n")
        self.write(brain / ".env", f"LAB_TOKEN={SECRET}\n", 0o600)
        self.write(brain / ".brain-private", "nothing-secret-here\n")
        self.edit_brain_json(brain, lambda d: d["privacy"].update(private_file_expected=True))
        self.git(brain, "add", "-A")
        self.git(brain, "commit", "-q", "-m", "meta(brain): record the expectation")
        self.git(brain, "push", "-q")
        r = self.doctor(brain)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.found(r, WARN), [], r.stdout)
        self.assertTrue(self.found(r, OK, ".env"), r.stdout)

    def test_findings_never_echo_an_env_value(self):
        brain = self.make_brain()
        self.write(brain / ".env.example", "LAB_TOKEN=\nLAB_HOST=\n")
        self.write(brain / ".env", f"LAB_HOST={SECRET}\n", 0o644)
        r = self.doctor(brain)
        self.assertTrue(self.found(r, WARN, ".env", "LAB_TOKEN"), r.stdout)
        self.assertNotIn(SECRET, r.stdout + r.stderr)

    def test_manifest_edits_are_listed_and_capped(self):
        brain = self.make_brain()
        for i in range(12):
            self.write(brain / "_meta" / "extra" / f"added-{i:02d}.txt", "x\n")
        found = self.in_process(brain, quick=True)
        lines = self.has(found, WARN, "manifest")
        self.assertEqual(len(lines), 1, found)
        self.assertIn("12 ", lines[0].message)
        self.assertIn("brain-upstream", lines[0].message)
        self.assertIn("more", lines[0].message)


class SourceTest(DoctorCase):
    def advance(self, template: Path) -> str:
        self.git(template, "commit", "-q", "--allow-empty", "-m", "a newer template")
        return self.git(template, "rev-parse", "--short", "HEAD").strip()

    def test_local_path_source(self):
        brain = self.make_brain()
        template = self.template_of(brain)
        found = self.in_process(brain, quick=True)
        self.assertTrue(self.has(found, OK, "source"), found)
        self.assertFalse(self.has(found, WARN, "source"), found)

        newer = self.advance(template)
        found = self.in_process(brain, quick=True)  # a local path is read even with --quick
        warned = self.has(found, WARN, "source")
        self.assertEqual(len(warned), 1, found)
        self.assertIn(newer, warned[0].message)
        self.assertIn("update", warned[0].message)

    def test_unreachable_local_source_is_skipped(self):
        brain = self.make_brain()
        self.write(brain / "brain.local.json", json.dumps({"template": {"source": str(self.tmp / "gone")}}))
        found = self.in_process(brain, quick=False)
        self.assertTrue(self.has(found, OK, "source", "skipped"), found)

    def test_no_source_is_skipped(self):
        brain = self.make_brain()
        (brain / "brain.local.json").unlink()
        found = self.in_process(brain, quick=False)
        self.assertTrue(self.has(found, OK, "source", "skipped"), found)

    def test_a_broken_brain_local_json_is_skipped(self):
        brain = self.make_brain()
        (brain / "brain.local.json").write_text("{ nope", encoding="utf-8")
        found = self.in_process(brain, quick=False)
        self.assertTrue(self.has(found, OK, "source", "skipped"), found)

    def test_url_source_is_read_with_ls_remote(self):
        brain = self.make_brain()
        template = self.template_of(brain)
        url = template.resolve().as_uri()  # file:///... is a URL as far as git is concerned
        self.write(brain / "brain.local.json", json.dumps({"template": {"source": url}}))
        found = self.in_process(brain, quick=False)
        self.assertTrue(self.has(found, OK, "source", "up to date"), found)

        newer = self.advance(template)
        found = self.in_process(brain, quick=False)
        warned = self.has(found, WARN, "source")
        self.assertEqual(len(warned), 1, found)
        self.assertIn(newer, warned[0].message)

    def test_ls_remote_has_a_ten_second_timeout(self):
        brain = self.make_brain()
        url = self.template_of(brain).resolve().as_uri()
        self.write(brain / "brain.local.json", json.dumps({"template": {"source": url}}))
        real = gitutil.git
        calls = []

        def spy(cwd, *args, **kwargs):
            calls.append((args, kwargs))
            return real(cwd, *args, **kwargs)

        with mock.patch("brainlib.doctor.gitutil.git", side_effect=spy):
            self.in_process(brain, quick=False)
        remote = [kwargs for args, kwargs in calls if args and args[0] == "ls-remote"]
        self.assertEqual(len(remote), 1, calls)
        self.assertEqual(remote[0].get("timeout"), 10)

    def test_unreachable_url_is_skipped_and_never_shows_credentials(self):
        brain = self.make_brain()
        url = "https://user:" + SECRET + "@example.invalid/org/template.git"
        self.write(brain / "brain.local.json", json.dumps({"template": {"source": url}}))
        real = gitutil.git

        def offline(cwd, *args, **kwargs):
            if args and args[0] == "ls-remote":
                raise gitutil.GitError(args, f"fatal: unable to access '{url}': timed out")
            return real(cwd, *args, **kwargs)

        with mock.patch("brainlib.doctor.gitutil.git", side_effect=offline):
            found = self.in_process(brain, quick=False)
        self.assertTrue(self.has(found, OK, "source", "skipped"), found)
        self.assertNotIn(SECRET, " ".join(f.message for f in found))

    def test_ls_remote_never_prompts(self):
        brain = self.make_brain()
        self.write(brain / "brain.local.json",
                   json.dumps({"template": {"source": "git@example.invalid:org/template.git"}}))
        self.git(brain, "config", "core.sshCommand", "ssh -i my-key")
        seen = {}
        real = gitutil.git

        def spy(cwd, *args, **kwargs):
            if args and args[0] == "ls-remote":
                seen["prompt"] = os.environ.get("GIT_TERMINAL_PROMPT")
                seen["ssh"] = os.environ.get("GIT_SSH_COMMAND")
                raise gitutil.GitError(args, "no network")
            return real(cwd, *args, **kwargs)

        with mock.patch("brainlib.doctor.gitutil.git", side_effect=spy):
            found = self.in_process(brain, quick=False)
        self.assertEqual(seen.get("prompt"), "0")  # no password prompt on the terminal
        self.assertEqual(seen.get("ssh"), "ssh -i my-key -o BatchMode=yes")  # no host-key question; their key kept
        self.assertNotIn("GIT_TERMINAL_PROMPT", os.environ)  # put back afterwards
        self.assertNotIn("GIT_SSH_COMMAND", os.environ)
        self.assertTrue(self.has(found, OK, "source", "skipped"), found)

    def test_git_timeout_raises_git_error(self):
        bin_dir = self.tmp / "fake bin"
        bin_dir.mkdir()
        fake = bin_dir / "git"
        fake.write_text("#!/bin/sh\nexec sleep 5\n", encoding="utf-8")
        os.chmod(str(fake), 0o755)
        started = time.monotonic()
        with mock.patch.dict(os.environ, {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}):
            with self.assertRaises(gitutil.GitError) as raised:
                gitutil.git(self.tmp, "ls-remote", "somewhere", timeout=0.5)
        self.assertIn("timed out", raised.exception.stderr)
        self.assertLess(time.monotonic() - started, 4)


class ScriptTestsTest(DoctorCase):
    def fake_python(self, brain: Path, exit_code: int, output: str = "") -> Path:
        record = brain / "python-called.txt"
        script = brain / "bin" / "py"
        self.write(script,
                   f'#!/bin/sh\n{{ pwd -P; printf "%s\\n" "$@"; }} > "{record}"\n'
                   f"printf '%s' '{output}' >&2\nexit {exit_code}\n", 0o755)
        self.edit_brain_json(brain, lambda d: d.setdefault("scripts", {}).update(python="bin/py"))
        return record

    def test_runs_the_pinned_command_under_scripts_python(self):
        brain = self.make_brain()
        record = self.fake_python(brain, 5)  # what Python 3.12+ does when it finds nothing
        r = self.doctor(brain)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.found(r, OK, "script tests", "no script tests yet"), r.stdout)
        called = record.read_text(encoding="utf-8").splitlines()
        self.assertEqual(called[0], os.path.realpath(str(brain)))
        self.assertEqual(called[1:], ["-m", "unittest", "discover", "-s", "scripts/tests", "-t", "scripts"])

    def test_older_python_that_ran_nothing_is_also_no_tests_yet(self):
        brain = self.make_brain()
        self.fake_python(brain, 0, "Ran 0 tests in 0.000s\n\nOK\n")
        r = self.doctor(brain)
        self.assertTrue(self.found(r, OK, "script tests", "no script tests yet"), r.stdout)

    def test_no_scripts_tests_folder_is_no_tests_yet(self):
        brain = self.make_brain()
        shutil.rmtree(str(brain / "scripts" / "tests"))
        found = self.in_process(brain)
        self.assertTrue(self.has(found, OK, "script tests", "no script tests yet"), found)

    def test_passing_tests_are_counted(self):
        brain = self.make_brain()
        self.write(brain / "scripts" / "tests" / "test_fine.py",
                   "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_fine(self):\n"
                   "        self.assertTrue(True)\n")
        found = self.in_process(brain)
        self.assertTrue(self.has(found, OK, "script tests", "1 test passes"), found)
        self.assertEqual(list((brain / "scripts").rglob("__pycache__")), [])  # running them leaves nothing behind

    def test_a_failure_names_the_test_but_prints_no_output(self):
        brain = self.make_brain()
        self.write(brain / "scripts" / "tests" / "test_leaky.py",
                   "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_leaky(self):\n"
                   f"        self.fail('{SECRET}')\n")
        found = self.in_process(brain)
        blocked = self.has(found, BLOCK, "script tests", "failed")
        self.assertEqual(len(blocked), 1, found)
        self.assertIn("test_leaky", blocked[0].message)
        self.assertNotIn(SECRET, blocked[0].message)


class QuickTest(DoctorCase):
    def test_quick_skips_tests_nested_and_network(self):
        brain = self.make_brain()
        # Each of these would be reported by a full run ...
        self.write(brain / "scripts" / "tests" / "test_fail.py",
                   "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_fail(self):\n"
                   "        self.fail('x')\n")
        self.nested_repo(brain)
        template = self.template_of(brain)
        self.write(brain / "brain.local.json", json.dumps({"template": {"source": template.resolve().as_uri()}}))
        self.git(template, "commit", "-q", "--allow-empty", "-m", "newer")

        full = self.doctor(brain)
        self.assertEqual(full.returncode, 1)
        self.assertTrue(self.found(full, BLOCK, "script tests"), full.stdout)
        self.assertTrue(self.found(full, WARN, "projects/app"), full.stdout)
        self.assertTrue(self.found(full, WARN, "source"), full.stdout)

        # ... and --quick runs none of them.
        quick = self.doctor(brain, "--quick")
        self.assertEqual(quick.returncode, 0, quick.stdout + quick.stderr)
        self.assertEqual(self.found(quick, None, "projects/app"), [], quick.stdout)
        self.assertEqual(self.found(quick, WARN, "source"), [], quick.stdout)
        for subject in ("script tests", "nested repos", "source"):
            self.assertTrue(self.found(quick, OK, subject, "--quick"), (subject, quick.stdout))

    def test_quick_makes_no_subprocess_beyond_git_and_no_ls_remote_or_walk(self):
        brain = self.make_brain()
        self.nested_repo(brain)
        url = self.template_of(brain).resolve().as_uri()
        self.write(brain / "brain.local.json", json.dumps({"template": {"source": url}}))
        real = gitutil.git
        verbs = []

        def spy(cwd, *args, **kwargs):
            verbs.append(args[0] if args else "")
            return real(cwd, *args, **kwargs)

        with mock.patch("brainlib.doctor.gitutil.git", side_effect=spy), \
                mock.patch.object(doctor, "subprocess", mock.Mock(run=mock.Mock(side_effect=AssertionError("ran")))), \
                mock.patch("brainlib.doctor.gitutil.nested_repos", side_effect=AssertionError("walked")):
            found = doctor.checks(brain, config.load(brain), True)
        self.assertNotIn("ls-remote", verbs)
        self.assertFalse([f for f in found if f.severity == BLOCK], found)


class ReadOnlyTest(DoctorCase):
    def test_read_only(self):
        brain = self.make_brain()
        # Make everything a check might want to touch dirty or stale: a changed tracked file, an untracked one,
        # an .env with loose permissions, a nested repo whose index is out of date.
        self.write(brain / "README.md", "# changed\n")
        self.write(brain / "stray.txt", "x\n")
        self.write(brain / ".env.example", "LAB_TOKEN=\n")
        self.write(brain / ".env", f"LAB_HOST={SECRET}\n", 0o644)
        repo = self.nested_repo(brain)
        for tracked in (brain / "docs" / "README.md", repo / "main.txt"):  # same bytes, new mtime: `git status`
            later = time.time() + 120                                      # would refresh the index and rewrite it
            os.utime(str(tracked), (later, later))
        indexes = [brain / ".git" / "index", repo / ".git" / "index"]
        before_index = [os.stat(str(p)).st_mtime_ns for p in indexes]
        before = self.snapshot(brain)

        for args in ((), ("--quick",)):
            r = self.doctor(brain, *args)
            self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
        self.in_process(brain, quick=False)

        self.assertEqual(self.snapshot(brain), before)
        self.assertEqual([os.stat(str(p)).st_mtime_ns for p in indexes], before_index)
        self.assertEqual(list(brain.rglob("__pycache__")), [])
        self.assertEqual(list(brain.rglob("*.lock")), [])


class ApiTest(DoctorCase):
    def test_findings_are_plain_findings(self):
        brain = self.make_brain()
        found = self.in_process(brain, quick=True)
        self.assertTrue(found)
        self.assertTrue(all(isinstance(f, Finding) for f in found))
        self.assertTrue(all(f.severity in (OK, WARN, BLOCK) for f in found))

    def test_summary_helper(self):
        found = [Finding(OK, "a", "x"), Finding(WARN, "b", "y"), Finding(WARN, "c", "z"), Finding(BLOCK, "d", "w")]
        self.assertEqual(doctor.summary(found), "doctor: 1 block, 2 warn")


if __name__ == "__main__":
    unittest.main()
