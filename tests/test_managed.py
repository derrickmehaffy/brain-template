from __future__ import annotations

import copy
import shlex
import unittest

from tests.helpers import TEMPLATE_ROOT, TempDirCase

from brainlib import managed

META = TEMPLATE_ROOT / "_meta"


class UpsertTest(unittest.TestCase):
    def test_markers_are_the_pinned_strings(self):
        self.assertEqual(
            managed.MD_BEGIN, "<!-- brain:begin — managed by the brain template; edit below the end marker -->")
        self.assertEqual(managed.MD_END, "<!-- brain:end -->")
        self.assertEqual(managed.GI_BEGIN, "# <!-- brain:begin --> managed by the brain template; edit below the end marker")
        self.assertEqual(managed.GI_END, "# <!-- brain:end -->")

    def test_upsert_inserts_at_top(self):
        out = managed.upsert("# Title\n\nbody\n", "md", "- one\n- two\n")
        self.assertEqual(out, f"{managed.MD_BEGIN}\n- one\n- two\n{managed.MD_END}\n\n# Title\n\nbody\n")

    def test_upsert_inserts_at_top_of_gitignore(self):
        out = managed.upsert("# mine\nnotes/\n", "gitignore", "/*\n!/docs/")
        self.assertEqual(out, f"{managed.GI_BEGIN}\n/*\n!/docs/\n{managed.GI_END}\n\n# mine\nnotes/\n")

    def test_upsert_into_empty_text(self):
        self.assertEqual(managed.upsert("", "md", "- one"), f"{managed.MD_BEGIN}\n- one\n{managed.MD_END}\n")

    def test_upsert_leaves_one_blank_line_even_when_the_text_starts_blank(self):
        out = managed.upsert("\n\n# Title\n", "md", "- one")
        self.assertEqual(out, f"{managed.MD_BEGIN}\n- one\n{managed.MD_END}\n\n# Title\n")

    def test_upsert_replaces_and_keeps_outside_text(self):
        old = f"above\n\n{managed.MD_BEGIN}\n- old one\n- old two\n{managed.MD_END}\n\n# Mine\n\nbelow\n"
        out = managed.upsert(old, "md", "- new")
        self.assertEqual(out, f"above\n\n{managed.MD_BEGIN}\n- new\n{managed.MD_END}\n\n# Mine\n\nbelow\n")

    def test_upsert_replaces_a_block_whose_begin_wording_changed(self):
        # A later template may reword the begin marker; the old block must still be found.
        old = "<!-- brain:begin — an older wording -->\n- old\n<!-- brain:end -->\n\n# Mine\n"
        out = managed.upsert(old, "md", "- new")
        self.assertEqual(out, f"{managed.MD_BEGIN}\n- new\n{managed.MD_END}\n\n# Mine\n")

    def test_upsert_replaces_in_a_gitignore(self):
        old = f"{managed.GI_BEGIN}\n/*\n{managed.GI_END}\ndocs/private/\n"
        out = managed.upsert(old, "gitignore", "/*\n!/docs/")
        self.assertEqual(out, f"{managed.GI_BEGIN}\n/*\n!/docs/\n{managed.GI_END}\ndocs/private/\n")

    def test_kinds_do_not_see_each_others_markers(self):
        text = f"{managed.GI_BEGIN}\n/*\n{managed.GI_END}\n"
        out = managed.upsert(text, "md", "- one")
        self.assertTrue(out.startswith(managed.MD_BEGIN + "\n"))
        self.assertIn(managed.GI_BEGIN, out)

    def test_upsert_idempotent(self):
        once = managed.upsert("# Title\n", "md", "- one\n- two\n")
        self.assertEqual(managed.upsert(once, "md", "- one\n- two\n"), once)
        gi = managed.upsert("# mine\n", "gitignore", "/*\n")
        self.assertEqual(managed.upsert(gi, "gitignore", "/*\n"), gi)

    def test_begin_without_end_raises(self):
        with self.assertRaises(managed.ManagedError):
            managed.upsert(f"{managed.MD_BEGIN}\n- one\n\n# Mine\n", "md", "- new")
        with self.assertRaises(managed.ManagedError):
            managed.upsert(f"{managed.GI_BEGIN}\n/*\n", "gitignore", "/*")

    def test_end_without_begin_raises(self):
        with self.assertRaises(managed.ManagedError):
            managed.upsert(f"# Mine\n{managed.MD_END}\n", "md", "- new")

    def test_two_blocks_raise(self):
        block = f"{managed.MD_BEGIN}\n- one\n{managed.MD_END}\n"
        with self.assertRaises(managed.ManagedError):
            managed.upsert(block + "\n" + block, "md", "- new")

    def test_unknown_kind_raises(self):
        with self.assertRaises(managed.ManagedError):
            managed.upsert("", "toml", "x")

    def test_crlf_kept(self):
        text = "# Title\r\n\r\nbody\r\n"
        out = managed.upsert(text, "md", "- one\n- two\n")
        self.assertEqual(out, f"{managed.MD_BEGIN}\r\n- one\r\n- two\r\n{managed.MD_END}\r\n\r\n# Title\r\n\r\nbody\r\n")
        self.assertNotIn("\n", out.replace("\r\n", ""))  # no bare line feed anywhere
        again = managed.upsert(out, "md", "- three")
        self.assertEqual(again, f"{managed.MD_BEGIN}\r\n- three\r\n{managed.MD_END}\r\n\r\n# Title\r\n\r\nbody\r\n")

    def test_replace_keeps_outside_bytes_of_a_crlf_file(self):
        text = f"{managed.MD_BEGIN}\r\n- old\r\n{managed.MD_END}\r\n\r\n# Mine\r\n"
        out = managed.upsert(text, "md", "- new")
        self.assertEqual(out, f"{managed.MD_BEGIN}\r\n- new\r\n{managed.MD_END}\r\n\r\n# Mine\r\n")

    def test_lf_file_stays_lf(self):
        self.assertNotIn("\r", managed.upsert("# Title\n", "md", "- one\n- two\n"))

    def test_odd_line_separators_in_outside_text_are_not_line_breaks(self):
        # str.splitlines() would treat these as breaks and shift the block; only \n counts.
        text = f"a\x0cb c\n\n{managed.MD_BEGIN}\n- old\n{managed.MD_END}\nz\x0bz\n"
        out = managed.upsert(text, "md", "- new")
        self.assertEqual(out, f"a\x0cb c\n\n{managed.MD_BEGIN}\n- new\n{managed.MD_END}\nz\x0bz\n")


class BlockFilesTest(TempDirCase):
    def test_block_body_reads_the_shipped_files(self):
        md = managed.block_body(META, "md")
        self.assertTrue(md.startswith("- This folder is a brain"))
        self.assertIn("Secret names: `_meta/brain env-sync --list`.", " ".join(md.split()))
        self.assertFalse(md.endswith("\n"))
        gi = managed.block_body(META, "gitignore")
        self.assertEqual(gi.splitlines()[0], "/*")
        self.assertIn("__pycache__/", gi.splitlines())
        self.assertIn("*.pyc", gi.splitlines())

    def test_block_files_hold_no_markers(self):
        for kind in ("md", "gitignore"):
            body = managed.block_body(META, kind)
            self.assertNotIn("brain:begin", body)
            self.assertNotIn("brain:end", body)

    def test_block_body_unknown_kind_raises(self):
        with self.assertRaises(managed.ManagedError):
            managed.block_body(META, "toml")

    def test_block_body_missing_file_raises_managed_error(self):
        with self.assertRaises(managed.ManagedError):
            managed.block_body(self.tmp, "md")

    def test_shipped_blocks_round_trip_through_upsert(self):
        for kind in ("md", "gitignore"):
            body = managed.block_body(META, kind)
            once = managed.upsert("# mine\n", kind, body)
            self.assertEqual(managed.upsert(once, kind, body), once)

    def test_gitignore_block_allowlist_behaviour(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        (repo / ".gitignore").write_text(
            managed.upsert("# The brain's own rules go below.\n", "gitignore", managed.block_body(META, "gitignore")),
            encoding="utf-8")
        tracked = [
            ".gitignore", "brain.json", "CLAUDE.md", "README.md", ".env.example",
            ".claude/settings.json", ".claude/skills/lab-x/SKILL.md",
            "_meta/brain", "_meta/brainlib/cli.py", "docs/README.md", "scripts/a/b.py",
        ]
        ignored = [
            ".env", ".env.local", "scripts/.env", "notes.txt", "project/readme.md", "tests/t.py",
            ".claude/settings.local.json", "_meta/brainlib/__pycache__/x.pyc", "scripts/mod.pyc",
            ".brain/gate.log", "brain.local.json", ".brain-private", "local/brains.txt",
        ]
        for rel in tracked + ignored:
            path = repo / rel
            if not path.exists():  # `.gitignore` is the file under test
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x\n", encoding="utf-8")
        shown = self.git(repo, "ls-files", "--others", "--exclude-standard").split("\n")
        self.assertEqual(sorted(p for p in shown if p), sorted(tracked))


class MergeSettingsTest(unittest.TestCase):
    PRE = {"matcher": managed.PRE_MATCHER,
           "hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR/_meta/brain" gate check'}]}
    POST = {"matcher": managed.POST_MATCHER,
            "hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR/_meta/brain" gate record'}]}

    def test_constants(self):
        self.assertEqual(managed.DENY, ["Read(./.env)", "Read(./.env.*)"])
        self.assertEqual(managed.HOOK_CMD, '"$CLAUDE_PROJECT_DIR/_meta/brain" gate {}')
        self.assertEqual(managed.PRE_MATCHER, "Write|Edit|MultiEdit|NotebookEdit|Bash")
        self.assertEqual(managed.POST_MATCHER, "Skill")

    def test_merge_into_empty_settings(self):
        self.assertEqual(managed.merge_settings({}), {
            "permissions": {"deny": ["Read(./.env)", "Read(./.env.*)"]},
            "hooks": {"PreToolUse": [self.PRE], "PostToolUse": [self.POST]},
        })

    def test_merge_settings_adds_once_keeps_foreign_and_replaces_stale(self):
        foreign_pre = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
        stale = {"matcher": "Write", "hooks": [
            {"type": "command", "command": '"/old/place/_meta/brain" gate check --old'}]}
        stop = {"hooks": [{"type": "command", "command": "notify-send done"}]}
        existing = {
            "model": "opus",
            "permissions": {"allow": ["Bash(ls)"], "deny": ["Read(./secrets)", "Read(./.env)"]},
            "hooks": {"PreToolUse": [foreign_pre, stale], "Stop": [stop]},
        }
        before = copy.deepcopy(existing)
        out = managed.merge_settings(existing)
        self.assertEqual(existing, before)  # pure: the input is not touched
        self.assertEqual(out["model"], "opus")
        self.assertEqual(out["permissions"]["allow"], ["Bash(ls)"])
        self.assertEqual(out["permissions"]["deny"], ["Read(./secrets)", "Read(./.env)", "Read(./.env.*)"])
        self.assertEqual(out["hooks"]["PreToolUse"], [foreign_pre, self.PRE])
        self.assertEqual(out["hooks"]["PostToolUse"], [self.POST])
        self.assertEqual(out["hooks"]["Stop"], [stop])
        self.assertEqual(managed.merge_settings(out), out)  # adding twice changes nothing

    def test_stale_hook_inside_a_shared_group_leaves_the_foreign_hook(self):
        mixed = {"matcher": "Bash", "hooks": [
            {"type": "command", "command": "echo mine"},
            {"type": "command", "command": '"$CLAUDE_PROJECT_DIR/_meta/brain" gate check'}]}
        out = managed.merge_settings({"hooks": {"PreToolUse": [mixed]}})
        self.assertEqual(out["hooks"]["PreToolUse"], [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}, self.PRE])

    def test_stale_gate_hook_under_another_event_is_dropped(self):
        stale = {"matcher": "Skill", "hooks": [{"type": "command", "command": '"/x/_meta/brain" gate record'}]}
        out = managed.merge_settings({"hooks": {"PostToolUse": [stale], "SubagentStop": [stale]}})
        self.assertEqual(out["hooks"]["PostToolUse"], [self.POST])
        self.assertNotIn("SubagentStop", out["hooks"])

    def test_foreign_hook_that_only_mentions_brain_is_kept(self):
        other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo gate is fine"}]}
        out = managed.merge_settings({"hooks": {"PreToolUse": [other]}})
        self.assertEqual(out["hooks"]["PreToolUse"], [other, self.PRE])

    def test_hook_command_is_quoted(self):
        command = managed.merge_settings({})["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(command, '"$CLAUDE_PROJECT_DIR/_meta/brain" gate check')
        # The project folder may contain a space: after expansion the script path is still one word.
        words = shlex.split(command.replace("$CLAUDE_PROJECT_DIR", "/a folder/with space"))
        self.assertEqual(words, ["/a folder/with space/_meta/brain", "gate", "check"])

    def test_record_hook_command(self):
        command = managed.merge_settings({})["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(command, '"$CLAUDE_PROJECT_DIR/_meta/brain" gate record')

    def test_malformed_settings_raise_instead_of_being_overwritten(self):
        for bad in ({"permissions": []}, {"permissions": {"deny": "x"}}, {"hooks": []},
                    {"hooks": {"PreToolUse": {}}}):
            with self.subTest(bad=bad):
                with self.assertRaises(managed.ManagedError):
                    managed.merge_settings(bad)


if __name__ == "__main__":
    unittest.main()
