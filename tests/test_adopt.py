from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import TEMPLATE_ROOT, TempDirCase  # first: puts <template>/_meta on sys.path
from tests import fixtures
from brainlib import config, hook, inventory, managed, manifest


def deep_snapshot(path) -> dict:
    """Every entry under `path` (folders and links included, `.git` included) -> (type, size, mtime_ns), and the
    folder itself as '.'. A file written, touched, replaced or removed anywhere changes it, and so does a folder
    that gained or lost an entry (a lock file git made and removed leaves its folder's mtime changed)."""
    path = Path(path)
    seen = {}
    for dirpath, dirnames, filenames in os.walk(str(path)):
        for name in dirnames + filenames:
            full = os.path.join(dirpath, name)
            st = os.lstat(full)
            kind = stat.S_IFMT(st.st_mode)
            seen[os.path.relpath(full, str(path))] = (kind, 0 if kind == stat.S_IFDIR else st.st_size, st.st_mtime_ns)
    st = os.lstat(str(path))
    seen["."] = (stat.S_IFDIR, 0, st.st_mtime_ns)
    return seen


class AdoptCase(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.env["BRAIN_LARGE_FOLDER_MB"] = "1"  # the fixture's 2 MiB Assets/ is then a large folder
        patcher = mock.patch.dict(os.environ, self.env, clear=True)  # for the calls these tests make in-process
        patcher.start()
        self.addCleanup(patcher.stop)
        self.template = self.copy_template()
        self.ws = self.tmp / "my workspace"
        self.facts = fixtures.build_workspace(self.ws, self.env)
        # Editors touch files in a real workspace, so each nested repo's index is out of date. A command that lets
        # git refresh it (git status does, unless told not to) would rewrite it, and a snapshot would show that.
        for rel in self.facts["nested"].values():
            os.utime(str(self.ws / rel / "log.txt"), (1_000_000_000, 1_000_000_000))

    # -- running adopt -----------------------------------------------------

    def adopt(self, *extra, dest=None, name="workspace", prefix="se2", description="My workspace", template=None):
        dest = self.ws if dest is None else dest
        args = ["adopt", str(dest), "--name", name, "--prefix", prefix]
        if description is not None:
            args += ["--description", description]
        return self.run_brain(self.template if template is None else template, *args, *extra)

    def adopted(self, *extra, **kwargs):
        r = self.adopt(*extra, **kwargs)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def refused(self, *extra, dest=None, **kwargs):
        """Run adopt, expect a refusal that left the folder and the template exactly as they were."""
        dest = self.ws if dest is None else dest
        before_dest, before_template = deep_snapshot(dest), deep_snapshot(self.template)
        r = self.adopt(*extra, dest=dest, **kwargs)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(deep_snapshot(dest), before_dest)
        self.assertEqual(deep_snapshot(self.template), before_template)
        return r

    def read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def lines(self, r):
        return [line.rstrip() for line in r.stdout.splitlines()]

    def gitignore_text(self, existing="") -> str:
        block = managed.block_body(TEMPLATE_ROOT / "_meta", "gitignore")
        return managed.upsert(existing, "gitignore", block)


class DryRunTest(AdoptCase):
    def test_dry_run_writes_nothing(self):
        before_ws, before_template = deep_snapshot(self.ws), deep_snapshot(self.template)
        r = self.adopted("--dry-run", "--private", "acme")
        self.assertEqual(deep_snapshot(self.ws), before_ws)  # nested .git/index mtimes and folder mtimes included
        self.assertNotIn("fixture-value", r.stdout + r.stderr)  # no value of .env, even though it is read for names
        self.assertEqual(deep_snapshot(self.template), before_template)  # not even local/brains.txt
        self.assertFalse((self.ws / ".git").exists())
        self.assertFalse((self.ws / "brain.json").exists())
        self.assertEqual(sorted(os.listdir(str(self.tmp / "os-tmp"))), [])  # the scratch folders are gone
        out = self.lines(r)
        self.assertTrue(any(line.startswith("dry run") and "nothing is written" in line for line in out), r.stdout)
        self.assertIn("alpha: remote", [line.strip() for line in out])  # the inventory is printed
        self.assertTrue(any("staging preview" in line for line in out), r.stdout)
        self.assertNotIn("no commit was made", r.stdout)  # that is the real run's closing line
        for rel in ("docs/ROUTING.md", "brain.json", "_meta/MANIFEST.sha256"):
            self.assertIn(rel, r.stdout)  # what would be written is listed

    def test_dry_run_in_a_folder_that_is_already_a_repo_leaves_its_index_alone(self):
        self.git(self.ws, "init", "-q")
        self.git(self.ws, "add", "docs/notes.md", "CLAUDE.md")
        self.git(self.ws, "commit", "-q", "-m", "notes")
        (self.ws / "docs" / "later.md").write_text("later\n", encoding="utf-8")
        os.utime(str(self.ws / "docs" / "notes.md"), (1_000_000_000, 1_000_000_000))  # the index is now stale
        before = deep_snapshot(self.ws)
        r = self.adopted("--dry-run")
        self.assertEqual(deep_snapshot(self.ws), before)
        self.assertIn("root git repo: yes", self.lines(r))

    def test_a_repo_inside_an_allowed_folder_is_neither_listed_nor_touched(self):
        vendored = fixtures.make_repo(self.ws / "docs" / "vendored", self.env, commits=2)
        os.utime(str(vendored / "log.txt"), (1_000_000_000, 1_000_000_000))
        before = deep_snapshot(self.ws)
        r = self.adopted("--dry-run")
        self.assertEqual(deep_snapshot(self.ws), before)
        self.assertIn("docs/vendored: no remote, 2 unpushed", [line.strip() for line in self.lines(r)])
        self.assertNotIn("docs/vendored/", r.stdout)
        self.assertNotIn("docs/vendored/log.txt", r.stdout)

    def test_dry_run_still_refuses(self):
        (self.ws / "brain.json").write_text("{}\n", encoding="utf-8")
        before = deep_snapshot(self.ws)
        r = self.adopt("--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already a brain", r.stderr)
        self.assertEqual(deep_snapshot(self.ws), before)
        r = self.adopt("--dry-run", dest=self.tmp / "missing")
        self.assertEqual(r.returncode, 1)
        r = self.adopt("--dry-run", prefix="brain")
        self.assertEqual(r.returncode, 1)  # the argument checks run first

    def test_dry_run_reports_what_it_would_keep_and_the_problems_a_real_run_would_hit(self):
        (self.ws / ".claude").mkdir(exist_ok=True)
        (self.ws / ".claude" / "settings.json").write_text("{ not json", encoding="utf-8")
        (self.ws / "README.md").write_text("mine\n", encoding="utf-8")
        before = deep_snapshot(self.ws)
        r = self.adopted("--dry-run")
        self.assertEqual(deep_snapshot(self.ws), before)
        out = self.lines(r)
        self.assertTrue(any(re.match(r"ok +README\.md: kept", line) for line in out), r.stdout)
        self.assertTrue(any(re.match(r"WARN +\.claude/settings\.json: ", line) for line in out), r.stdout)


class InventoryLinesTest(AdoptCase):
    def test_inventory_lines(self):
        r = self.adopted("--dry-run")
        out = [line.strip() for line in self.lines(r)]
        self.assertIn("root git repo: no", out)
        self.assertIn("nested git repos: 3", out)
        self.assertIn("alpha: remote", out)
        self.assertIn("beta: no remote, 1 unpushed", out)
        self.assertIn("work/team/gamma: remote, 2 unpushed", out)  # two folders down, found and described
        large = [line for line in out if line.startswith("Assets:")]
        self.assertEqual(large, ["Assets: 2 MB"])
        self.assertTrue(any(line.startswith("large top-level folders") and "over 1 MB" in line for line in out), out)
        existing = next(line for line in out if line.startswith("already there:"))
        for item in (".claude/skills/", "CLAUDE.md", "docs/", ".env"):
            self.assertIn(item, existing)

    def test_scan_and_render(self):
        inv = inventory.scan(self.ws)
        self.assertEqual([path for path, _ in inv.nested], ["alpha", "beta", "work/team/gamma"])
        states = {path: (state.has_remote, state.unpushed) for path, state in inv.nested}
        self.assertEqual(states, {"alpha": (True, 0), "beta": (False, 1), "work/team/gamma": (True, 2)})
        self.assertEqual(inv.large, [("Assets", 2)])
        self.assertEqual(inv.existing, {".claude/skills": True, "CLAUDE.md": True, "docs": True, ".env": True})
        self.assertFalse(inv.root_is_repo)
        text = inventory.render(inv)
        self.assertIn("beta: no remote, 1 unpushed", text)
        self.assertNotIn("alpha: no remote", text)
        self.assertNotIn("alpha: remote,", text)  # nothing unpushed, so no count

    def test_a_folder_with_nothing_in_it_yet(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        inv = inventory.scan(empty)
        self.assertEqual((inv.nested, inv.large, inv.root_is_repo), ([], [], False))
        self.assertEqual(inv.existing, {".claude/skills": False, "CLAUDE.md": False, "docs": False, ".env": False})
        text = inventory.render(inv)
        self.assertIn("nested git repos: none", text)
        self.assertIn("already there: nothing", text)

    def test_the_large_folder_threshold(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("BRAIN_LARGE_FOLDER_MB", None)
            self.assertEqual(inventory.LARGE_FOLDER_MB, 100)
            self.assertEqual(inventory.large_folder_mb(), 100)
            self.assertEqual(inventory.scan(self.ws).large, [])  # 2 MiB is not large by default
            os.environ["BRAIN_LARGE_FOLDER_MB"] = "1"
            self.assertEqual(inventory.scan(self.ws).large, [("Assets", 2)])
            os.environ["BRAIN_LARGE_FOLDER_MB"] = "2"
            self.assertEqual(inventory.scan(self.ws).large, [])  # over, not at
            for junk in ("", "many", "-5"):
                os.environ["BRAIN_LARGE_FOLDER_MB"] = junk
                self.assertEqual(inventory.large_folder_mb(), 100, junk)

    def test_the_walk_stops_inside_a_repo_and_skips_links(self):
        fixtures.make_repo(self.ws / "alpha" / "vendor" / "inner", self.env)  # a repo inside a repo: not listed
        elsewhere = self.tmp / "elsewhere"
        fixtures.make_repo(elsewhere / "outside", self.env)
        (self.ws / "linked-in").symlink_to(self.ws / "work", target_is_directory=True)  # would list gamma twice
        (self.ws / "linked-out").symlink_to(elsewhere, target_is_directory=True)  # would list a repo outside
        (self.ws / "linked-big").symlink_to(self.ws / "Assets", target_is_directory=True)  # would be a 2nd large one
        inv = inventory.scan(self.ws)
        self.assertEqual([path for path, _ in inv.nested], ["alpha", "beta", "work/team/gamma"])
        self.assertEqual([name for name, _ in inv.large], ["Assets"])

    def test_scanning_leaves_every_repository_untouched(self):
        before = deep_snapshot(self.ws)
        inventory.scan(self.ws)
        self.assertEqual(deep_snapshot(self.ws), before)
        # the folder itself, when it is a repository whose index is stale: looking must not refresh it
        self.git(self.ws, "init", "-q")
        self.git(self.ws, "add", "docs/notes.md")
        os.utime(str(self.ws / "docs" / "notes.md"), (1_000_000_000, 1_000_000_000))  # stat data now differs
        before = deep_snapshot(self.ws)
        self.assertTrue(inventory.scan(self.ws).root_is_repo)
        self.assertEqual(deep_snapshot(self.ws), before)


class StagingPreviewTest(AdoptCase):
    def test_preview_excludes_nested_large_and_env(self):
        (self.ws / "docs" / "vendored").mkdir()
        fixtures.make_repo(self.ws / "docs" / "vendored", self.env)  # a repo inside an allowed folder
        listed = inventory.staging_preview(self.ws, self.gitignore_text(fixtures.GITIGNORE))
        names = [rel for rel, _ in listed]
        self.assertEqual(names, sorted(names))
        for rel in ("CLAUDE.md", ".gitignore", "docs/notes.md", fixtures.SKILL_PATH):
            self.assertIn(rel, names)
        for rel in names:
            self.assertFalse(rel.startswith(("alpha/", "beta/", "work/", "Assets/", "docs/vendored")), rel)
            self.assertFalse(rel.endswith("/"), rel)
            self.assertNotEqual(rel, ".env")
        self.assertEqual(dict(listed)["docs/notes.md"], len(fixtures.NOTES))

    def test_preview_names_with_spaces_newlines_and_unicode(self):
        odd = ["docs/with space.md", "docs/two\nlines.md", "docs/näme ☃.md"]
        for rel in odd:
            (self.ws / rel).write_text("x\n", encoding="utf-8")
        names = [rel for rel, _ in inventory.staging_preview(self.ws, self.gitignore_text())]
        for rel in odd:
            self.assertIn(rel, names)

    def test_preview_follows_the_ignore_text_it_is_given(self):
        # Nothing but `docs/` is un-ignored by this text, so only what is under it is listed.
        text = "/*\n!/docs/\n"
        names = [rel for rel, _ in inventory.staging_preview(self.ws, text)]
        self.assertEqual(names, ["docs/notes.md"])
        # A rule the person's own .gitignore adds is honoured as well (git reads the file in the folder).
        (self.ws / "docs" / "scratch.tmp").write_text("x", encoding="utf-8")
        (self.ws / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
        names = [rel for rel, _ in inventory.staging_preview(self.ws, "")]
        self.assertNotIn("docs/scratch.tmp", names)
        self.assertIn("docs/notes.md", names)

    def test_preview_writes_nothing_in_the_folder_and_cleans_up_after_itself(self):
        scratch = self.tmp / "os-tmp"
        self.git(self.ws, "init", "-q")
        before = deep_snapshot(self.ws)
        with mock.patch.object(tempfile, "tempdir", str(scratch)):
            inventory.staging_preview(self.ws, self.gitignore_text())
        self.assertEqual(deep_snapshot(self.ws), before)
        self.assertEqual(os.listdir(str(scratch)), [])

    def test_preview_is_what_git_add_would_stage(self):
        self.adopted()
        real = self.git(self.ws, "ls-files", "-o", "--exclude-standard", "-z").split("\0")
        real = sorted(p for p in real if p)
        gitignore = (self.ws / ".gitignore").read_text(encoding="utf-8")
        shown = [rel for rel, _ in inventory.staging_preview(self.ws, gitignore)]
        self.assertEqual(shown, real)


class RealRunTest(AdoptCase):
    def test_keeps_existing_files(self):
        r = self.adopted()
        files = self.facts["files"]
        for rel in (fixtures.SKILL_PATH, "docs/notes.md", ".env"):
            self.assertEqual((self.ws / rel).read_bytes(), files[rel], rel)  # byte-identical
        claude = (self.ws / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(claude.startswith(managed.MD_BEGIN + "\n"))
        self.assertTrue(claude.endswith(managed.MD_END + "\n\n" + fixtures.CLAUDE_MD), claude)  # theirs, below
        ignore = (self.ws / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(ignore.startswith(managed.GI_BEGIN + "\n"))
        self.assertTrue(ignore.endswith(managed.GI_END + "\n\n" + fixtures.GITIGNORE), ignore)
        example = (self.ws / ".env.example").read_text(encoding="utf-8")
        self.assertIn("API_KEY=\n", example)
        self.assertNotIn("fixture-value", example)
        self.assertNotIn("fixture-value", r.stdout + r.stderr)  # a value is never printed
        # nothing was moved or renamed: the nested repos and the big folder are where they were
        for rel in ("alpha/.git", "beta/.git", "work/team/gamma/.git", "Assets/big.bin"):
            self.assertTrue((self.ws / rel).exists(), rel)

    def test_no_existing_file_changes_outside_the_managed_blocks(self):
        edited = {"CLAUDE.md", ".gitignore", ".claude/settings.json"}
        before = {}
        for dirpath, _dirnames, filenames in os.walk(str(self.ws)):
            for name in filenames:
                full = os.path.join(dirpath, name)
                rel = Path(os.path.relpath(full, str(self.ws))).as_posix()
                if rel not in edited:
                    before[rel] = (Path(full).read_bytes(), os.lstat(full).st_mtime_ns)
        self.assertIn(".env", before)
        self.assertIn("alpha/.git/index", before)
        self.adopted()
        for rel, (data, mtime) in before.items():
            self.assertEqual(Path(self.ws / rel).read_bytes(), data, rel)
            self.assertEqual(os.lstat(str(self.ws / rel)).st_mtime_ns, mtime, rel)

    def test_a_registry_that_cannot_be_written_is_a_warning_not_a_failure(self):
        shutil.rmtree(str(self.template / "local"))
        (self.template / "local").write_text("not a folder\n", encoding="utf-8")
        r = self.adopted()
        self.assertTrue(any(line.startswith("WARN") and "brains.txt" in line for line in self.lines(r)), r.stdout)
        self.assertTrue((self.ws / "brain.json").is_file())

    def test_a_failure_after_the_writes_began_says_what_stays_and_changes_nothing_of_theirs(self):
        self.git(self.ws, "init", "-q")
        shutil.rmtree(str(self.ws / ".git" / "hooks"))
        (self.ws / ".git" / "hooks").write_text("in the way\n", encoding="utf-8")  # the guard cannot be installed
        r = self.adopt()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("stopped", r.stderr)
        self.assertIn("hook", r.stderr)
        self.assertEqual((self.ws / "docs" / "notes.md").read_bytes(), self.facts["files"]["docs/notes.md"])
        self.assertTrue((self.ws / "brain.json").is_file())  # what was written stays, and is said to
        self.assertIn("stays", r.stderr)

    def test_writes_missing_skeleton_only(self):
        (self.ws / "README.md").write_text("my own readme\n", encoding="utf-8")
        (self.ws / "docs" / "ROUTING.md").write_text("my own routing\n", encoding="utf-8")
        (self.ws / ".env.example").write_text("EXISTING_NAME=\n", encoding="utf-8")
        r = self.adopted()
        self.assertEqual((self.ws / "README.md").read_text(encoding="utf-8"), "my own readme\n")
        self.assertEqual((self.ws / "docs" / "ROUTING.md").read_text(encoding="utf-8"), "my own routing\n")
        self.assertEqual((self.ws / ".env.example").read_text(encoding="utf-8"), "EXISTING_NAME=\n")
        out = self.lines(r)
        for rel in ("README.md", "docs/ROUTING.md", ".env.example"):
            self.assertTrue(any(re.match(r"ok +" + re.escape(rel) + r": kept", line) for line in out),
                            rel + "\n" + r.stdout)
        self.assertFalse(any(re.match(r"ok +docs/CAPABILITIES\.md: kept", line) for line in out))
        for rel in ("docs/README.md", "docs/CAPABILITIES.md", "docs/RETRO-LOG.md", "docs/UNCLASSIFIED-LOG.md",
                    "docs/UPSTREAM.md", "docs/practices/README.md", "docs/practices/INDEX.md", "scripts/README.md",
                    "scripts/tests/__init__.py", "_meta/brain", "_meta/VERSION", "brain.json", "brain.local.json",
                    "_meta/MANIFEST.sha256"):
            self.assertTrue((self.ws / rel).is_file(), rel)
        self.assertTrue(os.access(self.ws / "_meta" / "brain", os.X_OK))
        # the skeleton CLAUDE.md is only a starting point, so a CLAUDE.md that is there is never replaced by it
        self.assertNotIn("Folder map", (self.ws / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertIn("kept", r.stdout)

    def test_a_template_file_that_is_already_there_is_kept_and_flagged_as_a_local_edit(self):
        (self.ws / "_meta").mkdir()
        (self.ws / "_meta" / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        r = self.adopted()
        self.assertEqual((self.ws / "_meta" / "VERSION").read_text(encoding="utf-8"), "9.9.9\n")
        self.assertTrue(any(re.match(r"WARN +_meta/VERSION: kept, but it differs", line) for line in self.lines(r)),
                        r.stdout)
        self.assertEqual(manifest.local_edits(self.ws), ["_meta/VERSION"])  # update and doctor will say so too
        self.assertTrue((self.ws / "_meta" / "brain").is_file())  # the rest of the harness is there

    def test_skeleton_files_are_written_when_absent(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        (bare / "notes.txt").write_text("x\n", encoding="utf-8")
        self.adopted(dest=bare, name="bare", prefix="bar", description="Bare")
        claude = (bare / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(claude.startswith(managed.MD_BEGIN + "\n"))
        self.assertIn("# bare\n\nBare\n", claude)  # the filled skeleton sits below the block
        self.assertTrue((bare / ".gitignore").read_text(encoding="utf-8").startswith(managed.GI_BEGIN + "\n"))
        self.assertTrue((bare / ".env.example").is_file())  # no .env, so the skeleton's own
        self.assertEqual((bare / "notes.txt").read_text(encoding="utf-8"), "x\n")

    def test_brain_files(self):
        self.adopted("--private", "acme-corp")
        raw = self.read_json(self.ws / "brain.json")
        self.assertEqual((raw["name"], raw["prefix"], raw["description"]), ("workspace", "se2", "My workspace"))
        self.assertEqual(raw["scripts"], {"python": "python3", "packages": "stdlib-only"})
        self.assertTrue(raw["privacy"]["private_file_expected"])
        cfg = config.load(self.ws)
        self.assertEqual(cfg.role, "brain")
        self.assertEqual(cfg.private_patterns, ["acme-corp"])
        self.assertEqual(self.read_json(self.ws / "brain.local.json"), {"template": {"source": str(self.template)}})
        self.assertEqual(stat.S_IMODE(os.stat(str(self.ws / ".brain-private")).st_mode), 0o600)
        self.assertEqual(manifest.local_edits(self.ws), [])
        self.assertIn("_meta/brain", manifest.read(self.ws))
        self.assertNotIn("docs/ROUTING.md", manifest.read(self.ws))
        shim = self.ws / ".git" / "hooks" / "pre-commit"
        self.assertEqual(shim.read_text(encoding="utf-8"), hook.SHIM)
        self.assertTrue(os.access(shim, os.X_OK))

    def test_settings_merge_and_invalid_json(self):
        settings = self.ws / ".claude" / "settings.json"
        settings.write_text(json.dumps({"model": "mine", "permissions": {"allow": ["Bash(ls)"]}}), encoding="utf-8")
        self.adopted()
        merged = self.read_json(settings)
        self.assertEqual(merged["model"], "mine")
        self.assertEqual(merged["permissions"]["allow"], ["Bash(ls)"])
        self.assertEqual(merged["permissions"]["deny"], managed.DENY)
        self.assertEqual(merged["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
                         '"$CLAUDE_PROJECT_DIR/_meta/brain" gate check')
        self.assertEqual(merged["hooks"]["PostToolUse"][0]["hooks"][0]["command"],
                         '"$CLAUDE_PROJECT_DIR/_meta/brain" gate record')

        broken = self.tmp / "broken"
        (broken / ".claude").mkdir(parents=True)
        (broken / ".claude" / "settings.json").write_text("{ not json,", encoding="utf-8")
        r = self.adopted(dest=broken, name="broken", prefix="brk")
        self.assertEqual((broken / ".claude" / "settings.json").read_text(encoding="utf-8"), "{ not json,")
        warn = [line for line in self.lines(r) if line.startswith("WARN")]
        self.assertTrue(any(".claude/settings.json" in line and "not valid JSON" in line for line in warn), r.stdout)
        self.assertTrue((broken / "brain.json").is_file())  # the rest went on
        self.assertTrue((broken / "CLAUDE.md").read_text(encoding="utf-8").startswith(managed.MD_BEGIN))

    def test_settings_of_the_wrong_shape_refuse_before_anything_is_written(self):
        (self.ws / ".claude" / "settings.json").write_text("[1, 2]\n", encoding="utf-8")
        r = self.refused()
        self.assertIn("settings.json", r.stderr)

    def test_a_malformed_managed_block_refuses_before_anything_is_written(self):
        (self.ws / "CLAUDE.md").write_text(managed.MD_BEGIN + "\nhalf a block\n", encoding="utf-8")
        r = self.refused()
        self.assertIn("CLAUDE.md", r.stderr)
        self.assertIn("end marker", r.stderr)
        self.assertFalse((self.template / "local" / "brains.txt").exists())

    def test_no_commit(self):
        r = self.adopted()
        self.assertEqual(self.git(self.ws, "rev-list", "--all"), "")
        self.assertEqual(self.git(self.ws, "diff", "--cached", "--name-only"), "")  # nothing staged either
        self.assertEqual(self.git(self.ws, "ls-files"), "")
        self.assertTrue(any(line.startswith("no commit was made") for line in self.lines(r)), r.stdout)
        self.assertTrue((self.ws / ".git").is_dir())

    def test_a_folder_that_is_already_a_repo_keeps_its_history(self):
        self.git(self.ws, "init", "-q")
        self.git(self.ws, "add", "docs/notes.md")
        self.git(self.ws, "commit", "-q", "-m", "their history")
        head = self.git(self.ws, "rev-parse", "HEAD")
        r = self.adopted()
        self.assertEqual(self.git(self.ws, "rev-parse", "HEAD"), head)
        self.assertEqual(self.git(self.ws, "rev-list", "--count", "HEAD").strip(), "1")
        self.assertEqual(self.git(self.ws, "diff", "--cached", "--name-only"), "")
        self.assertIn("root git repo: yes", self.lines(r))
        self.assertEqual((self.ws / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8"), hook.SHIM)

    def test_registers(self):
        self.adopted()
        listed = (self.template / "local" / "brains.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(listed, [str(self.ws)])

    def test_preview_in_the_output(self):
        (self.ws / "docs" / "big.pdf").write_bytes(b"\0" * (1536 * 1024))  # over the 1024 KB default
        r = self.adopted()
        out = self.lines(r)
        self.assertTrue(any(re.match(r"staging preview: .*git add -A", line) for line in out), r.stdout)
        count = next(line for line in out if re.match(r"\s+\d+ files?, ", line))
        listed = self.git(self.ws, "ls-files", "-o", "--exclude-standard", "-z").split("\0")
        self.assertTrue(count.strip().startswith(f"{len([p for p in listed if p])} files, "), (count, listed))
        largest = out[out.index(next(line for line in out if "largest" in line)) + 1:]
        self.assertIn("docs/big.pdf", largest[0])  # the biggest first
        self.assertTrue(any(re.match(r"WARN +docs/big\.pdf: .*max_file_kb", line) for line in out), r.stdout)
        for line in out[out.index(next(line for line in out if line.startswith("staging preview"))):]:
            self.assertNotIn("Assets/", line)
            self.assertNotIn("alpha/", line)
            self.assertNotRegex(line, r"(^|\s)\.env(\s|$)")
        ten = [line for line in largest if re.match(r"\s+[\d.]+ (B|KB|MB|GB)  ", line)]
        self.assertLessEqual(len(ten), 10)

    def test_ten_largest_is_ten(self):
        for number in range(14):
            (self.ws / "docs" / f"f{number:02d}.md").write_text("x" * (100 + number), encoding="utf-8")
        r = self.adopted()
        out = self.lines(r)
        start = out.index(next(line for line in out if "largest" in line)) + 1
        shown = []
        for line in out[start:]:
            if not re.match(r"\s+[\d.]+ (B|KB|MB|GB)  ", line):
                break
            shown.append(line)
        self.assertEqual(len(shown), 10)

    def test_an_env_the_persons_own_ignore_rules_would_stage_is_called_out(self):
        (self.ws / ".gitignore").write_text("!.env\n", encoding="utf-8")  # sits below the block, so it wins
        r = self.adopted()
        out = self.lines(r)
        self.assertTrue(any(re.match(r"WARN +\.env: ", line) and "would be staged" in line for line in out), r.stdout)
        self.assertNotIn("fixture-value", r.stdout)

    def test_private_patterns(self):
        self.adopted("--private", "acme-corp", "--private", r"10\.20\.\d+\.\d+")
        lines = [line for line in (self.ws / ".brain-private").read_text(encoding="utf-8").splitlines()
                 if not line.startswith("#")]
        self.assertEqual(lines, ["acme-corp", r"10\.20\.\d+\.\d+"])
        self.assertNotIn(".brain-private", self.git(self.ws, "ls-files", "-o", "--exclude-standard"))

    def test_python_and_packages_options(self):
        self.adopted("--python", "/usr/bin/python3", "--packages", "allowed")
        raw = self.read_json(self.ws / "brain.json")
        self.assertEqual(raw["scripts"], {"python": "/usr/bin/python3", "packages": "allowed"})

    def test_a_second_adopt_is_refused_and_changes_nothing(self):
        self.adopted()
        before = deep_snapshot(self.ws)
        r = self.adopt()
        self.assertEqual(r.returncode, 1)
        self.assertIn("already a brain", r.stderr)
        self.assertEqual(deep_snapshot(self.ws), before)


class RefusalTest(AdoptCase):
    def test_refuses_existing_brain(self):
        (self.ws / "brain.json").write_text("{}\n", encoding="utf-8")
        r = self.refused()
        self.assertIn("already a brain", r.stderr)
        self.assertIn("update", r.stderr)

    def test_refuses_a_dangling_link_named_brain_json(self):
        (self.ws / "brain.json").symlink_to(self.tmp / "nowhere.json")
        self.assertIn("already a brain", self.refused().stderr)

    def test_refuses_outside_template(self):
        brain = self.fake_brain(prefix="lab")
        before = deep_snapshot(self.ws)
        r = self.adopt(template=brain)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("template checkout", r.stderr)
        self.assertEqual(deep_snapshot(self.ws), before)

    def test_refuses_the_template_itself(self):
        r = self.adopt(dest=self.template)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_refuses_a_folder_that_is_not_there(self):
        missing = self.tmp / "missing"
        r = self.adopt(dest=missing)
        self.assertEqual(r.returncode, 1)
        self.assertIn("new", r.stderr)  # points to the command for a new folder
        self.assertFalse(missing.exists())
        a_file = self.tmp / "a file"
        a_file.write_text("x", encoding="utf-8")
        r = self.adopt(dest=a_file)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a folder", r.stderr)
        self.assertEqual(a_file.read_text(encoding="utf-8"), "x")

    def test_refuses_bad_arguments(self):
        for kwargs in ({"prefix": "brain"}, {"prefix": "template"}, {"prefix": "A"}, {"prefix": "a-b"},
                       {"name": "two\nlines"}, {"name": "  "}, {"description": "one\r\ntwo"}):
            with self.subTest(kwargs=kwargs):
                self.refused(**kwargs)
        for pattern in ("(unclosed", "# a comment", "   ", "two\nlines"):
            with self.subTest(pattern=pattern):
                self.assertIn("--private", self.refused("--private", pattern).stderr)

    def test_a_usage_error_exits_2(self):
        for args in (["adopt", str(self.ws), "--prefix", "se2"],  # no --name
                     ["adopt", str(self.ws), "--name", "x"],  # no --prefix
                     ["adopt", "--name", "x", "--prefix", "se2"],  # no folder
                     ["adopt", str(self.ws), "--name", "x", "--prefix", "se2", "--packages", "maybe"]):
            with self.subTest(args=args):
                self.assertEqual(self.run_brain(self.template, *args).returncode, 2)

    def test_refuses_to_write_through_a_link_or_over_a_file(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "keep.txt").write_text("keep\n", encoding="utf-8")
        for name, make in (("docs", lambda p: p.symlink_to(elsewhere, target_is_directory=True)),
                           ("scripts", lambda p: p.write_text("a file where a folder goes\n", encoding="utf-8")),
                           ("_meta", lambda p: p.symlink_to(elsewhere, target_is_directory=True))):
            with self.subTest(name=name):
                folder = self.tmp / ("blocked-" + name)
                folder.mkdir()
                make(folder / name)
                before_elsewhere = deep_snapshot(elsewhere)
                r = self.refused(dest=folder)
                self.assertIn(name, r.stderr)
                self.assertEqual(deep_snapshot(elsewhere), before_elsewhere)

    def test_refuses_when_git_hooks_path_is_set(self):
        self.git(self.ws, "config", "--file", self.env["GIT_CONFIG_GLOBAL"], "core.hooksPath", "elsewhere")
        self.assertIn("core.hooksPath", self.refused().stderr)

    def test_refuses_a_folder_whose_repo_has_another_pre_commit_hook(self):
        self.git(self.ws, "init", "-q")
        hook_file = self.ws / ".git" / "hooks" / "pre-commit"
        hook_file.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        hook_file.chmod(0o755)
        r = self.refused()
        self.assertIn("pre-commit", r.stderr)
        self.assertEqual(hook_file.read_text(encoding="utf-8"), "#!/bin/sh\nexit 0\n")


class NestedRepoSafetyTest(AdoptCase):
    def test_a_real_run_leaves_every_nested_repo_alone(self):
        # Their working trees, indexes and refs are exactly what they were: adopt only looks at them.
        before = {rel: snap for rel, snap in deep_snapshot(self.ws).items()
                  if rel.split(os.sep)[0] in ("alpha", "beta", "work", "Assets")}
        self.adopted()
        after = {rel: snap for rel, snap in deep_snapshot(self.ws).items()
                 if rel.split(os.sep)[0] in ("alpha", "beta", "work", "Assets")}
        self.assertEqual(after, before)

    def test_git_location_variables_do_not_redirect_it(self):
        other = self.tmp / "other repo"
        other.mkdir()
        self.git(other, "init", "-q")
        env = dict(self.env, GIT_DIR=str(other / ".git"), GIT_WORK_TREE=str(other),
                   GIT_INDEX_FILE=str(other / ".git" / "index"))
        saved, self.env = self.env, env  # run_brain hands self.env to the child
        try:
            done = self.adopt()
        finally:
            self.env = saved
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((self.ws / ".git").is_dir())
        self.assertEqual(self.git(other, "ls-files"), "")


if __name__ == "__main__":
    unittest.main()
