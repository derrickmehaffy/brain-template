from __future__ import annotations

import json
import os
import re
import shutil
import stat
import unittest
from pathlib import Path

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config, install, managed, manifest

# A brain-owned file the update must leave alone, and the paths that are not part of the owned set.
NOT_OWNED = {"_meta/MANIFEST.sha256", "brain.json", "CLAUDE.md", ".gitignore", ".claude/settings.json"}


class UpdateCase(TempDirCase):
    def put(self, root, rel, text, mode=None) -> Path:
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if mode is not None:
            os.chmod(path, mode)
        return path

    def append(self, root, rel, text) -> Path:
        path = Path(root) / rel
        return self.put(root, rel, path.read_text(encoding="utf-8") + text)

    def commit(self, repo, message="change") -> str:
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", message)
        return self.git(repo, "rev-parse", "--short", "HEAD").strip()

    def pair(self, before=None):
        """(the template copy, a brain made from it). `before(template)` changes the template and its
        changes are committed before the brain is made."""
        template = self.copy_template()
        if before is not None:
            before(template)
            self.commit(template, "before the brain")
        dest = self.tmp / "my brain"
        made = self.run_brain(template, "new", str(dest), "--name", "homelab", "--prefix", "lab")
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        return template, dest

    def update(self, brain, *args):
        return self.run_brain(brain, "update", *args)

    def updated(self, brain, *args):
        r = self.update(brain, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def version_of(self, brain) -> str:
        return json.loads((brain / "brain.json").read_text(encoding="utf-8"))["template"]["version"]

    def owned_bytes(self, brain) -> dict:
        """Every file in the brain the template does not own, with its bytes."""
        found = {}
        for dirpath, dirnames, filenames in os.walk(str(brain)):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for name in filenames:
                full = Path(dirpath) / name
                rel = full.relative_to(brain).as_posix()
                if not manifest.is_shipped(rel) and rel not in NOT_OWNED:
                    found[rel] = full.read_bytes()
        return found

    def committed_shipped(self, template):
        return install.shipped(install.template_files(template))

    def status_paths(self, repo) -> set:
        out = self.git(repo, "status", "--porcelain", "--untracked-files=all")
        return {line[3:] for line in out.splitlines()}

    def assert_matches_template(self, brain, template):
        files = self.committed_shipped(template)
        self.assertEqual(sorted(manifest.read(brain)), sorted(files))
        self.assertEqual(manifest.local_edits(brain), [])
        for rel, (data, mode) in files.items():
            target = brain / rel
            self.assertEqual(target.read_bytes(), data, rel)
            self.assertEqual(bool(os.stat(target).st_mode & 0o111), bool(mode & 0o111), rel)


class ChangesTest(UpdateCase):
    def test_changes_only_template_owned(self):
        def before(t):
            self.put(t, "_meta/old-tool.txt", "going away\n")

        template, brain = self.pair(before)
        owned = self.owned_bytes(brain)
        head = self.git(brain, "rev-parse", "HEAD")
        settings = (brain / ".claude" / "settings.json").read_bytes()

        self.append(template, "_meta/brainlib/paths.py", "\n# changed by the template\n")
        self.put(template, "_meta/extra.txt", "added\n")
        (template / "_meta" / "old-tool.txt").unlink()
        self.append(template, "_meta/skeleton/docs/README.md", "\nA starter line.\n")
        self.put(template, "_meta/VERSION", "0.1.1\n")
        sha = self.commit(template)

        r = self.updated(brain)
        self.assertEqual(self.owned_bytes(brain), owned)  # byte-identical, README.md and docs/ included
        self.assertIn("# changed by the template", (brain / "_meta/brainlib/paths.py").read_text(encoding="utf-8"))
        self.assertEqual((brain / "_meta/extra.txt").read_text(encoding="utf-8"), "added\n")
        self.assertFalse((brain / "_meta/old-tool.txt").exists())
        self.assert_matches_template(brain, template)
        self.assertEqual((brain / ".claude" / "settings.json").read_bytes(), settings)
        self.assertEqual(self.version_of(brain), f"0.1.1+{sha}")
        self.assertEqual(config.load(brain).role, "brain")

        # nothing is committed, and only template-owned paths, the manifest and brain.json changed
        self.assertEqual(self.git(brain, "rev-parse", "HEAD"), head)
        touched = self.status_paths(brain)
        self.assertIn("_meta/extra.txt", touched)
        self.assertIn("_meta/old-tool.txt", touched)
        self.assertIn("brain.json", touched)
        self.assertEqual([p for p in touched if not manifest.is_shipped(p) and p not in NOT_OWNED], [])
        self.assertEqual(list(brain.rglob("*.brain-new")), [])

        for pattern in (rf"^\s*changed\s+_meta/brainlib/paths\.py$", rf"^\s*added\s+_meta/extra\.txt$",
                        rf"^\s*removed\s+_meta/old-tool\.txt$", rf"^\s*changed\s+brain\.json"):
            self.assertRegex(r.stdout, re.compile(pattern, re.M))
        self.assertIn("0.1.0", r.stdout)
        self.assertIn(f"0.1.1+{sha}", r.stdout)
        self.assertIn("nothing is committed", r.stdout)

    def test_up_to_date_writes_nothing(self):
        _, brain = self.pair()
        before = self.snapshot(brain)
        r = self.updated(brain)
        self.assertIn("already up to date", r.stdout)
        self.assertEqual(self.snapshot(brain), before)

    def test_an_update_after_the_previous_one_was_committed(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# one\n")
        self.commit(template)
        self.updated(brain)
        self.commit(brain, "meta(brain): update template")
        self.append(template, "_meta/brainlib/paths.py", "\n# two\n")
        sha = self.commit(template)
        self.updated(brain)
        self.assertTrue((brain / "_meta/brainlib/paths.py").read_text(encoding="utf-8").endswith("# two\n"))
        self.assertTrue(self.version_of(brain).endswith("+" + sha))
        self.assert_matches_template(brain, template)

    def test_exec_bit_kept(self):
        template, brain = self.pair()
        self.append(template, "_meta/brain", "# a comment the template added\n")
        self.put(template, "_meta/new-tool", "#!/bin/sh\necho hi\n", mode=0o755)
        self.commit(template)
        self.updated(brain)
        for rel in ("_meta/brain", "_meta/new-tool"):
            self.assertTrue(os.stat(brain / rel).st_mode & stat.S_IXUSR, rel)
        self.assertFalse(os.stat(brain / "_meta/VERSION").st_mode & stat.S_IXUSR)
        after = self.run_brain(brain, "--version")  # still a working harness
        self.assertEqual(after.returncode, 0, after.stdout + after.stderr)
        self.assert_matches_template(brain, template)

    def test_a_mode_only_change_is_applied(self):
        template, brain = self.pair()
        os.chmod(template / "_meta" / "gates.json", 0o755)
        self.commit(template)
        self.updated(brain)
        self.assertTrue(os.stat(brain / "_meta/gates.json").st_mode & stat.S_IXUSR)
        self.assert_matches_template(brain, template)

    def test_removals_prune_empty_folders(self):
        def before(t):
            self.put(t, "_meta/gone/deep/c.txt", "c\n")

        template, brain = self.pair(before)
        self.assertTrue((brain / "_meta/gone/deep/c.txt").is_file())
        self.git(template, "rm", "-q", "-r", "_meta/gone")
        self.commit(template)
        self.updated(brain)
        self.assertFalse((brain / "_meta" / "gone").exists())
        self.assert_matches_template(brain, template)

    def test_a_file_becomes_a_folder_and_back(self):
        def before(t):
            self.put(t, "_meta/thing", "a file\n")
            self.put(t, "_meta/area/a.txt", "a\n")
            self.put(t, "_meta/area/sub/b.txt", "b\n")

        template, brain = self.pair(before)
        (template / "_meta" / "thing").unlink()
        self.put(template, "_meta/thing/inner.txt", "inner\n")
        self.git(template, "rm", "-q", "-r", "_meta/area")
        self.put(template, "_meta/area", "now a file\n")
        self.commit(template)
        self.updated(brain)
        self.assertEqual((brain / "_meta/thing/inner.txt").read_text(encoding="utf-8"), "inner\n")
        self.assertEqual((brain / "_meta/area").read_text(encoding="utf-8"), "now a file\n")
        self.assert_matches_template(brain, template)

    def test_runs_in_a_brain_whose_path_has_a_space_and_so_does_the_template(self):
        template, brain = self.pair()
        self.assertIn(" ", str(brain))
        self.assertIn(" ", str(template))
        self.append(template, "_meta/brainlib/paths.py", "\n# spaced\n")
        self.commit(template)
        self.updated(brain)
        self.assert_matches_template(brain, template)


class SourceTest(UpdateCase):
    def test_never_copies_uncommitted_template_edit(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# committed\n")
        self.commit(template)
        committed_config = (template / "_meta/brainlib/config.py").read_bytes()
        self.append(template, "_meta/brainlib/config.py", "\n# an edit nobody committed\n")  # unstaged
        self.append(template, "_meta/brainlib/hook.py", "\n# a staged edit\n")
        self.git(template, "add", "_meta/brainlib/hook.py")
        self.put(template, "_meta/untracked.txt", "never committed\n")
        self.put(template, "_meta/VERSION", "9.9.9\n")
        self.put(template, "_meta/CHANGELOG.md", "# Changelog\n\n## 9.9.9 — 2026-01-01\n\n- An unreleased line.\n")

        r = self.updated(brain)
        self.assertEqual((brain / "_meta/brainlib/config.py").read_bytes(), committed_config)
        self.assertNotIn("an edit nobody committed", (brain / "_meta/brainlib/config.py").read_text(encoding="utf-8"))
        self.assertNotIn("a staged edit", (brain / "_meta/brainlib/hook.py").read_text(encoding="utf-8"))
        self.assertFalse((brain / "_meta/untracked.txt").exists())
        self.assertIn("# committed", (brain / "_meta/brainlib/paths.py").read_text(encoding="utf-8"))
        self.assertNotIn("9.9.9", self.version_of(brain))
        self.assertNotIn("9.9.9", r.stdout)
        self.assertNotIn("unreleased", r.stdout)
        self.assertEqual(manifest.local_edits(brain), [])

    def test_uses_default_branch(self):
        template, brain = self.pair()
        self.put(template, "_meta/on-main.txt", "main\n")
        self.commit(template)
        self.git(template, "checkout", "-q", "-b", "wip")
        self.put(template, "_meta/on-wip.txt", "wip\n")
        self.commit(template)

        dry = self.updated(brain, "--dry-run", "--ref", "wip")  # an explicit ref beats the default branch
        self.assertIn("_meta/on-wip.txt", dry.stdout)

        self.updated(brain)  # the checked-out branch is wip; the default branch is main
        self.assertTrue((brain / "_meta/on-main.txt").is_file())
        self.assertFalse((brain / "_meta/on-wip.txt").exists())

    def test_ref_reads_a_tag_and_a_sha_and_warns_on_a_downgrade(self):
        template, brain = self.pair()
        self.put(template, "_meta/VERSION", "0.1.1\n")
        self.put(template, "_meta/one.txt", "one\n")
        first = self.commit(template)
        self.git(template, "tag", "v1")
        self.put(template, "_meta/VERSION", "0.2.0\n")
        self.put(template, "_meta/two.txt", "two\n")
        second = self.commit(template)

        self.updated(brain, "--ref", "v1")
        self.assertEqual(self.version_of(brain), f"0.1.1+{first}")
        self.assertTrue((brain / "_meta/one.txt").is_file())
        self.assertFalse((brain / "_meta/two.txt").exists())
        self.commit(brain, "meta(brain): update template to v1")

        self.updated(brain, "--ref", second)
        self.assertEqual(self.version_of(brain), f"0.2.0+{second}")
        self.commit(brain, "meta(brain): update template to second")

        r = self.updated(brain, "--ref", "v1")
        self.assertRegex(r.stdout, r"WARN\s+update: .*older")
        self.assertFalse((brain / "_meta/two.txt").exists())

    def test_unknown_ref_refuses_and_writes_nothing(self):
        template, brain = self.pair()
        before = self.snapshot(brain)
        r = self.update(brain, "--ref", "no-such-ref")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no-such-ref", r.stderr)
        r = self.update(brain, "--ref=--upload-pack=x")  # never handed to git as an option
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stderr.startswith("update: "), r.stderr)
        r = self.update(brain, "--from", template.as_uri(), "--ref=--upload-pack=x")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.snapshot(brain), before)
        self.assertEqual(list((self.tmp / "os-tmp").iterdir()), [])

    def test_from_url(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# from a url\n")
        self.put(template, "_meta/VERSION", "0.1.1\n")
        sha = self.commit(template)
        (brain / "brain.local.json").unlink()  # no known source: only --from can say where
        self.assertEqual(self.update(brain).returncode, 1)

        uri = template.as_uri()
        self.assertTrue(uri.startswith("file://"))
        r = self.updated(brain, "--from", uri)
        self.assertIn("# from a url", (brain / "_meta/brainlib/paths.py").read_text(encoding="utf-8"))
        self.assertEqual(self.version_of(brain), f"0.1.1+{sha}")
        self.assert_matches_template(brain, template)
        self.assertEqual(list((self.tmp / "os-tmp").iterdir()), [])  # the temporary clone is gone
        self.assertEqual(self.git(template, "status", "--porcelain"), "")

    def test_from_url_never_sees_uncommitted_edits_and_takes_a_ref(self):
        template, brain = self.pair()
        self.put(template, "_meta/one.txt", "one\n")
        self.commit(template)
        self.git(template, "tag", "v1")
        self.put(template, "_meta/two.txt", "two\n")
        self.commit(template)
        self.append(template, "_meta/brainlib/paths.py", "\n# uncommitted\n")
        self.updated(brain, "--from", template.as_uri(), "--ref", "v1")
        self.assertTrue((brain / "_meta/one.txt").is_file())
        self.assertFalse((brain / "_meta/two.txt").exists())
        self.assertNotIn("uncommitted", (brain / "_meta/brainlib/paths.py").read_text(encoding="utf-8"))
        self.assertEqual(list((self.tmp / "os-tmp").iterdir()), [])

    def test_an_unreachable_url_refuses_and_leaves_no_temporary_files(self):
        _, brain = self.pair()
        before = self.snapshot(brain)
        r = self.update(brain, "--from", (self.tmp / "nowhere").as_uri())
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stderr.startswith("update: "), r.stderr)
        self.assertEqual(self.snapshot(brain), before)
        self.assertEqual(list((self.tmp / "os-tmp").iterdir()), [])

    def test_from_a_path_that_is_not_a_template_refuses(self):
        _, brain = self.pair()
        before = self.snapshot(brain)
        plain = self.tmp / "plain folder"
        plain.mkdir()
        for source in (plain, self.tmp / "missing"):
            r = self.update(brain, "--from", str(source))
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertTrue(r.stderr.startswith("update: "), r.stderr)
        repo = self._new_dir("other")  # a repository that is not the brain template
        self.git(repo, "init", "-q")
        self.put(repo, "README.md", "hello\n")
        self.commit(repo)
        r = self.update(brain, "--from", str(repo))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("template", r.stderr)
        self.assertEqual(self.snapshot(brain), before)

    def test_credentials_in_a_url_are_never_printed(self):
        _, brain = self.pair()
        secret = "s3" + "cr3t" + "value"
        r = self.update(brain, "--from", f"https://user:{secret}@127.0.0.1:1/none.git")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn(secret, r.stdout + r.stderr)
        self.assertEqual(list((self.tmp / "os-tmp").iterdir()), [])

    def test_a_source_that_git_could_read_as_an_option_or_a_command_is_refused(self):
        _, brain = self.pair()
        before = self.snapshot(brain)
        marker = self.tmp / "ran"
        for source in ("-oProxyCommand@host:x", "--upload-pack=touch", f"ext::sh -c touch% {marker}"):
            with self.subTest(source=source):
                r = self.update(brain, f"--from={source}")
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("neither a folder nor a git URL", r.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.snapshot(brain), before)

    def test_no_source_exits_1(self):
        _, brain = self.pair()
        (brain / "brain.local.json").unlink()
        r = self.update(brain)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no template source: pass --from", r.stderr)

    def test_from_beats_the_configured_source(self):
        template, brain = self.pair()
        self.put(template, "_meta/one.txt", "one\n")
        self.commit(template)
        local = json.loads((brain / "brain.local.json").read_text(encoding="utf-8"))
        local["template"]["source"] = str(self.tmp / "stale")
        (brain / "brain.local.json").write_text(json.dumps(local), encoding="utf-8")
        self.assertEqual(self.update(brain).returncode, 1)  # the configured source is gone
        self.updated(brain, "--from", str(template))
        self.assertTrue((brain / "_meta/one.txt").is_file())

    def test_refuses_in_the_template(self):
        template = self.copy_template()
        before = self.snapshot(template)
        r = self.update(template, "--from", str(template))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("brain", r.stderr)
        self.assertEqual(self.snapshot(template), before)


class RefusalTest(UpdateCase):
    def test_refuses_on_local_edit_and_writes_nothing(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/config.py", "\n# the template moved on\n")
        self.commit(template)
        self.append(brain, "_meta/brainlib/paths.py", "\n# a local edit\n")
        self.put(brain, ".claude/skills/brain-mine/SKILL.md", "a hand-made skill\n")
        before = self.snapshot(brain)

        r = self.update(brain)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("_meta/brainlib/paths.py", r.stderr)
        self.assertIn(".claude/skills/brain-mine/SKILL.md", r.stderr)
        self.assertIn("brain-upstream", r.stderr)
        self.assertEqual(self.snapshot(brain), before)  # nothing at all was written
        self.assertEqual(list(brain.rglob("*.brain-new")), [])

    def test_refuses_on_a_missing_template_file(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/config.py", "\n# the template moved on\n")
        self.commit(template)
        (brain / "_meta" / "gates.json").unlink()
        r = self.update(brain)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("_meta/gates.json", r.stderr)

    def test_refuses_on_uncommitted_changes_under_shipped_paths(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# one\n")
        self.put(template, "_meta/VERSION", "0.1.1\n")
        self.commit(template)
        self.updated(brain)  # leaves its changes uncommitted, as designed

        self.append(template, "_meta/brainlib/paths.py", "\n# two\n")
        self.put(template, "_meta/VERSION", "0.1.2\n")
        self.commit(template)
        before = self.snapshot(brain)
        r = self.update(brain)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("uncommitted", r.stderr)
        self.assertIn("_meta/brainlib/paths.py", r.stderr)
        self.assertIn("brain-sync", r.stderr)  # the way out: commit the earlier update
        self.assertEqual(self.snapshot(brain), before)

        self.commit(brain, "meta(brain): update template to 0.1.1")
        self.updated(brain)
        self.assertTrue(self.version_of(brain).startswith("0.1.2+"))

    def test_an_uncommitted_new_brain_is_refused_too(self):
        # adopt stops before its first commit; until then every shipped file is untracked
        template, brain = self.pair()
        shutil.rmtree(brain / ".git")
        self.git(brain, "init", "-q")
        self.append(template, "_meta/brainlib/paths.py", "\n# one\n")
        self.commit(template)
        before = self.snapshot(brain)
        r = self.update(brain)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("uncommitted", r.stderr)
        self.assertEqual(self.snapshot(brain), before)

    def test_a_brain_that_is_not_a_repo_skips_the_git_check(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# one\n")
        self.commit(template)
        shutil.rmtree(brain / ".git")
        self.updated(brain)
        self.assert_matches_template(brain, template)

    def test_a_broken_managed_block_refuses_before_writing(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# one\n")
        self.commit(template)
        claude = brain / "CLAUDE.md"
        claude.write_text(claude.read_text(encoding="utf-8").replace(managed.MD_END, ""), encoding="utf-8")
        before = self.snapshot(brain)
        r = self.update(brain)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("CLAUDE.md", r.stderr)
        self.assertEqual(self.snapshot(brain), before)

    def test_a_wrongly_shaped_settings_file_refuses_before_writing(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# one\n")
        self.commit(template)
        (brain / ".claude" / "settings.json").write_text('{"hooks": []}\n', encoding="utf-8")
        before = self.snapshot(brain)
        r = self.update(brain)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("settings.json", r.stderr)
        self.assertEqual(self.snapshot(brain), before)

    def test_settings_that_are_not_json_are_left_alone_with_a_warning(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# one\n")
        self.commit(template)
        (brain / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
        r = self.updated(brain)
        self.assertRegex(r.stdout, r"WARN\s+update: .*settings\.json")
        self.assertEqual((brain / ".claude" / "settings.json").read_text(encoding="utf-8"), "{not json")
        self.assert_matches_template(brain, template)


class DryRunTest(UpdateCase):
    def test_dry_run(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# changed\n")
        self.put(template, "_meta/extra.txt", "added\n")
        self.put(template, "_meta/VERSION", "0.1.1\n")
        self.commit(template)
        brain_before, template_before = self.snapshot(brain), self.snapshot(template)

        r = self.updated(brain, "--dry-run")
        self.assertTrue(r.stdout.startswith("dry run: nothing is written"), r.stdout)
        self.assertRegex(r.stdout, re.compile(r"^\s*changed\s+_meta/brainlib/paths\.py$", re.M))
        self.assertRegex(r.stdout, re.compile(r"^\s*added\s+_meta/extra\.txt$", re.M))
        self.assertEqual(self.snapshot(brain), brain_before)
        self.assertEqual(self.snapshot(template), template_before)
        self.assertEqual(list((self.tmp / "os-tmp").iterdir()), [])

    def test_dry_run_still_refuses_on_a_local_edit(self):
        template, brain = self.pair()
        self.append(brain, "_meta/brainlib/paths.py", "\n# a local edit\n")
        before = self.snapshot(brain)
        r = self.update(brain, "--dry-run")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.snapshot(brain), before)

    def test_dry_run_from_url_leaves_nothing_behind(self):
        template, brain = self.pair()
        self.put(template, "_meta/extra.txt", "added\n")
        self.commit(template)
        before = self.snapshot(brain)
        self.updated(brain, "--dry-run", "--from", template.as_uri())
        self.assertEqual(self.snapshot(brain), before)
        self.assertEqual(list((self.tmp / "os-tmp").iterdir()), [])


class BlocksTest(UpdateCase):
    def test_refreshes_managed_blocks_and_settings_only(self):
        template, brain = self.pair()
        claude = brain / "CLAUDE.md"
        original = claude.read_text(encoding="utf-8")
        after_block = original.split(managed.MD_END, 1)[1]
        claude.write_text(original.replace("Call skills", "CALL SKILLS", 1) + "\nMy own rule.\n", encoding="utf-8")
        ignore = brain / ".gitignore"
        ignore.write_text(ignore.read_text(encoding="utf-8") + "my-private-dir/\n", encoding="utf-8")
        settings_path = brain / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["model"] = "a-model"
        settings["permissions"] = {"allow": ["Bash(ls)"], "deny": ["Read(./private)"]}
        del settings["hooks"]
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
        raw_before = json.loads((brain / "brain.json").read_text(encoding="utf-8"))
        owned = self.owned_bytes(brain)

        self.append(template, "_meta/managed/CLAUDE.block.md", "\nA managed line the template added.\n")
        self.append(template, "_meta/managed/gitignore.block", "\nnew-ignored-thing/\n")
        self.put(template, "_meta/VERSION", "0.1.1\n")
        sha = self.commit(template)
        r = self.updated(brain)

        text = claude.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(managed.MD_BEGIN + "\n"))
        self.assertIn("A managed line the template added.", text.split(managed.MD_END, 1)[0])
        self.assertNotIn("CALL SKILLS", text.split(managed.MD_END, 1)[0])  # the edit inside the block is gone
        self.assertEqual(text.split(managed.MD_END, 1)[1], after_block + "\nMy own rule.\n")
        gitignore = ignore.read_text(encoding="utf-8")
        self.assertTrue(gitignore.startswith(managed.GI_BEGIN + "\n"))
        self.assertIn("new-ignored-thing/", gitignore.split(managed.GI_END, 1)[0])
        self.assertTrue(gitignore.endswith("my-private-dir/\n"))

        merged = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(merged["model"], "a-model")
        self.assertEqual(merged["permissions"]["allow"], ["Bash(ls)"])
        self.assertEqual(merged["permissions"]["deny"], ["Read(./private)", *managed.DENY])
        self.assertEqual(merged["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
                         '"$CLAUDE_PROJECT_DIR/_meta/brain" gate check')
        self.assertEqual(merged["hooks"]["PostToolUse"][0]["hooks"][0]["command"],
                         '"$CLAUDE_PROJECT_DIR/_meta/brain" gate record')

        raw_after = json.loads((brain / "brain.json").read_text(encoding="utf-8"))
        self.assertEqual(raw_after["template"], {"source": None, "version": f"0.1.1+{sha}"})
        raw_after["template"] = raw_before["template"]
        self.assertEqual(raw_after, raw_before)  # nothing but template.version changed in brain.json
        self.assertEqual(self.owned_bytes(brain), owned)
        for rel in ("CLAUDE.md", ".gitignore", ".claude/settings.json"):
            self.assertRegex(r.stdout, re.compile(rf"^\s*changed\s+{re.escape(rel)}", re.M))

    def test_unchanged_blocks_and_settings_are_not_rewritten(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# one\n")
        self.commit(template)
        before = {rel: os.stat(brain / rel).st_mtime_ns for rel in ("CLAUDE.md", ".gitignore", ".claude/settings.json")}
        r = self.updated(brain)
        after = {rel: os.stat(brain / rel).st_mtime_ns for rel in before}
        self.assertEqual(before, after)
        self.assertNotRegex(r.stdout, r"changed\s+CLAUDE\.md")

    def test_a_block_that_is_missing_is_added_at_the_top(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# one\n")
        self.commit(template)
        (brain / "CLAUDE.md").write_text("# Mine\n\nOnly my own text.\n", encoding="utf-8")
        self.updated(brain)
        text = (brain / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith(managed.MD_BEGIN + "\n"))
        self.assertTrue(text.endswith("# Mine\n\nOnly my own text.\n"))


class ReportTest(UpdateCase):
    UPSTREAM = (
        "# Upstream suggestions\n\n"
        "## 2026-11-03-lands\n- template: 0.1.0\n- files: _meta/brain\n- status: open\n### What happened\nx\n\n"
        "## 2026-11-03-declined\n- template: 0.1.0\n- files: _meta/brain\n- status: open\n### What happened\nx\n\n"
        "## 2026-11-03-unanswered\n- template: 0.1.0\n- files: _meta/brain\n- status: open\n### What happened\nx\n\n"
        "## 2026-11-03-taken-in\n- template: 0.1.0\n- files: _meta/brain\n- status: landed 0.1.1\n### What happened\nx\n"
    )
    CHANGELOG = (
        "# Changelog\n\n"
        "## 0.1.1 — 2026-11-05\n\n"
        "- landed: 2026-11-03-lands — the gate now checks Bash writes\n"
        "- declined: 2026-11-03-declined — fits only one brain\n"
        "- landed: 2026-11-03-taken-in — already flipped in the brain\n"
        "- landed: 2026-11-09-someone-elses — another brain's suggestion\n\n"
        "## 0.1.0 — 2026-11-02\n\n- First version.\n"
    )

    def test_reports_changelog_and_answered_ids(self):
        template, brain = self.pair()
        (brain / "docs" / "UPSTREAM.md").write_text(self.UPSTREAM, encoding="utf-8")
        self.put(template, "_meta/CHANGELOG.md", self.CHANGELOG)
        self.put(template, "_meta/VERSION", "0.1.1\n")
        self.commit(template)

        r = self.updated(brain)
        out = r.stdout
        self.assertIn("## 0.1.1", out)
        self.assertIn("- landed: 2026-11-03-lands — the gate now checks Bash writes", out)
        self.assertNotIn("First version.", out)  # 0.1.0 is not newer than the installed version
        self.assertRegex(out, re.compile(r"^answered  2026-11-03-lands  landed 0\.1\.1$", re.M))
        self.assertRegex(out, re.compile(r"^answered  2026-11-03-declined  declined: fits only one brain$", re.M))
        self.assertNotIn("2026-11-03-unanswered", out)
        self.assertNotRegex(out, r"answered  2026-11-03-taken-in")  # not open any more
        self.assertNotRegex(out, r"answered  2026-11-09-someone-elses")  # not this brain's
        self.assertEqual((brain / "docs" / "UPSTREAM.md").read_text(encoding="utf-8"), self.UPSTREAM)  # not flipped

    def test_the_new_changelog_reaches_the_brain_for_upstream_list(self):
        template, brain = self.pair()
        (brain / "docs" / "UPSTREAM.md").write_text(self.UPSTREAM, encoding="utf-8")
        self.put(template, "_meta/CHANGELOG.md", self.CHANGELOG)
        self.put(template, "_meta/VERSION", "0.1.1\n")
        self.commit(template)
        self.updated(brain)
        r = self.run_brain(brain, "upstream", "list")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"{brain}  2026-11-03-lands  open  answer: landed 0.1.1", r.stdout)

    def test_semver_order_in_the_report(self):
        template, brain = self.pair()
        self.put(template, "_meta/CHANGELOG.md", (
            "# Changelog\n\n## 0.10.0 — 2026-12-01\n\n- ten\n\n## 0.9.0 — 2026-11-20\n\n- nine\n\n"
            "## 0.1.0 — 2026-11-02\n\n- First version.\n"))
        self.put(template, "_meta/VERSION", "0.10.0\n")
        self.commit(template)
        r = self.updated(brain)
        self.assertLess(r.stdout.index("## 0.10.0"), r.stdout.index("## 0.9.0"))
        self.assertIn("- nine", r.stdout)
        self.assertNotIn("First version.", r.stdout)

    def test_reports_changed_skeleton_files(self):
        template, brain = self.pair()
        owned = self.owned_bytes(brain)
        ignore_before = (brain / ".gitignore").read_bytes()
        self.append(template, "_meta/skeleton/docs/README.md", "\nA new starter line.\n")
        self.append(template, "_meta/skeleton/gitignore", "starter-only/\n")
        self.put(template, "_meta/skeleton/docs/NEW.md", "a new starter file\n")
        self.git(template, "rm", "-q", "_meta/skeleton/docs/RETRO-LOG.md")
        self.commit(template)

        r = self.updated(brain)
        # reported by the path they take in a brain, with the dotfile renamed back
        for rel, verb in (("docs/README.md", "changed"), (".gitignore", "changed"), ("docs/NEW.md", "added"),
                          ("docs/RETRO-LOG.md", "removed")):
            self.assertRegex(r.stdout, re.compile(rf"^\s*{verb}\s+{re.escape(rel)}\s+\(_meta/skeleton/", re.M), rel)
        self.assertNotIn("docs/ROUTING.md", r.stdout)
        # and none of them reaches the brain's own files
        self.assertEqual(self.owned_bytes(brain), owned)
        self.assertFalse((brain / "docs" / "NEW.md").exists())
        self.assertEqual((brain / ".gitignore").read_bytes(), ignore_before)
        # the starter files themselves are template-owned copies, and are kept current
        self.assertTrue((brain / "_meta/skeleton/docs/NEW.md").is_file())
        self.assert_matches_template(brain, template)

    def test_a_recorded_sha_that_is_not_in_the_templates_history_is_harmless(self):
        # a brain made from a GitHub template copy records the sha of its own HEAD, which the template never had
        template, brain = self.pair()
        raw = json.loads((brain / "brain.json").read_text(encoding="utf-8"))
        raw["template"]["version"] = "0.1.0+" + "0" * 7
        (brain / "brain.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        self.append(template, "_meta/skeleton/docs/README.md", "\nA new starter line.\n")
        self.put(template, "_meta/CHANGELOG.md", self.CHANGELOG)
        self.put(template, "_meta/VERSION", "0.1.1\n")
        sha = self.commit(template)
        r = self.updated(brain)
        self.assertIn("## 0.1.1", r.stdout)
        self.assertNotIn("First version.", r.stdout)  # decided by the version number, not the sha
        self.assertRegex(r.stdout, re.compile(r"^\s*changed\s+docs/README\.md\s+\(_meta/skeleton/", re.M))
        self.assertEqual(self.version_of(brain), f"0.1.1+{sha}")
        self.assert_matches_template(brain, template)

    def test_no_skeleton_section_when_the_skeleton_is_unchanged(self):
        template, brain = self.pair()
        self.append(template, "_meta/brainlib/paths.py", "\n# one\n")
        self.commit(template)
        r = self.updated(brain)
        self.assertNotIn("skeleton", r.stdout)


if __name__ == "__main__":
    unittest.main()
