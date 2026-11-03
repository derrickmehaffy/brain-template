from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config, rename, routing_sync
from brainlib.report import BROKEN

FENCE = "`" * 3
CALL = "**Call it directly when:**"
BODY = f"Does the thing; hands on to lab-a and to lab-ab.\n\n{CALL} when the person names it.\n\n## Done when\n\n- it is done\n"

MAP = "\n".join([
    "# Routing map", "", FENCE + "mermaid",
    "flowchart LR",
    "IN(a request):::entry --> lab-router:::work",
    "lab-router --> lab-a:::work",
    "lab-router --> lab-ab:::work",
    "lab-a --> lab-c:::work",
    "lab-ab --> lab-c",
    FENCE, "",
])

RULES = {
    "rules": [{"when": {"kind": ["a"]}, "skill": "lab-a", "why": "a goes to lab-a"}],
    "default": "lab-ab",
    "cases": [{"input": {"kind": ["a"]}, "expect": "lab-a"}],
}

# written by hand so the test can tell that the file's own layout survives the rewrite
BRAIN_JSON = (
    '{ "name": "lab test brain", "prefix": "lab", "description": "A brain for tests",\n'
    '  "gates": [ {"path": "docs/notes/**", "skills": ["lab-a", "lab-ab"], "why": "lab-a writes them"} ],\n'
    '  "gate_exempt": [ ".claude/skills/lab-a/tmp/**" ]\n'
    '}\n'
)

OLD_CLAUDE_MD = "# Map\n\n- `lab-a` does the thing; `lab-ab` is the other one.\n"


def write(root: Path, rel: str, text: str) -> Path:
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def read(root: Path, rel: str) -> str:
    return (Path(root) / rel).read_text(encoding="utf-8")


class RenameCase(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        # direct calls shell out to git too: keep them off the person's git config, as the CLI runs are
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def bare(self, role=None, prefix="lab", skills=()) -> Path:
        """A brain holding exactly these (name, body) skills and an empty map, whatever the working tree ships."""
        root = self.fake_brain(prefix=prefix, role=role)
        shutil.rmtree(str(root / ".claude" / "skills"), ignore_errors=True)
        meta_map = root / "_meta" / "ROUTING-META.md"
        if meta_map.exists():
            meta_map.unlink()
        write(root, "docs/ROUTING.md", "# Routing map\n")
        for name, body in skills:
            self.make_skill(root, name, "Does X. Use when Y.", body)
        return root

    def brain(self, extra_skills=()) -> Path:
        """The `lab` fixture: a router, lab-a, its look-alike lab-ab and lab-c, and the files that name them."""
        names = ("lab-router", "lab-a", "lab-ab", "lab-c")
        root = self.bare(skills=[(name, BODY) for name in names] + list(extra_skills))
        write(root, "brain.json", BRAIN_JSON)
        write(root, "docs/ROUTING.md", MAP)
        write(root, ".claude/skills/lab-router/rules.json", json.dumps(RULES, indent=2) + "\n")
        write(root, ".claude/skills/lab-a/references/notes.md", "See lab-a for the details.\n")
        write(root, "CLAUDE.md", OLD_CLAUDE_MD)
        write(root, "README.md", "Nothing about skills here.\n")
        write(root, "docs/NOTES.md", "Mentions `lab-a` once and lab-ab once.\n")
        write(root, "docs/RETRO-LOG.md", "| 2026-01-01 | lab-a was slow |\n")
        write(root, "scripts/run.py", "# called by lab-a\nprint('hi')\n")
        return root

    def load(self, root: Path) -> config.Config:
        return config.load(root)

    def block_of(self, root: Path, name: str) -> str:
        text = read(root, f".claude/skills/{name}/SKILL.md")
        start = text.index(routing_sync.BEGIN)
        return text[start:text.index(routing_sync.END, start) + len(routing_sync.END)]


class PlanTest(RenameCase):
    def test_dry_run_lists_and_changes_nothing(self):
        root = self.brain()
        before = self.snapshot(root)
        plan = rename.plan(root, self.load(root), "lab-a", "lab-d")
        self.assertEqual(plan, sorted(plan))
        self.assertTrue(all(isinstance(rel, str) and isinstance(n, int) and n > 0 for rel, n in plan))
        self.assertIn(("docs/ROUTING.md", 2), plan)
        self.assertEqual(self.snapshot(root), before)

    def test_cli_dry_run_lists_files_and_changes_nothing(self):
        root = self.brain()
        before = self.snapshot(root)
        r = self.run_brain(root, "rename-skill", "lab-a", "lab-d")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("docs/ROUTING.md", r.stdout)
        self.assertIn(".claude/skills/lab-router/rules.json", r.stdout)
        self.assertIn("brain.json", r.stdout)
        self.assertNotIn("RETRO-LOG", r.stdout)
        self.assertIn("--apply", r.stdout)
        self.assertEqual(self.snapshot(root), before)
        self.assertTrue((root / ".claude/skills/lab-a").is_dir())
        self.assertFalse((root / ".claude/skills/lab-d").exists())

    def test_word_boundary(self):
        root = self.brain()
        write(root, "docs/words.md",
              "lab-a lab-ab lab-a-b xlab-a lab-a2 pre-lab-a (lab-a) `lab-a`, lab-a. skills/lab-a/SKILL.md lab-a:::work\n")
        plan = dict(rename.plan(root, self.load(root), "lab-a", "lab-d"))
        self.assertEqual(plan["docs/words.md"], 6)
        rename.apply(root, self.load(root), "lab-a", "lab-d")
        self.assertEqual(read(root, "docs/words.md"),
                         "lab-d lab-ab lab-a-b xlab-a lab-a2 pre-lab-a (lab-d) `lab-d`, lab-d. skills/lab-d/SKILL.md lab-d:::work\n")

    def test_scope_leaves_out_history_other_trees_and_template_owned_skills(self):
        root = self.brain(extra_skills=[("brain-sample", "Mentions lab-a in an example.\n")])
        write(root, "_meta/note.txt", "lab-a\n")
        write(root, "tests/test_x.py", "# lab-a\n")
        write(root, "docs/sub/RETRO-LOG.md", "lab-a\n")   # only the log at docs/RETRO-LOG.md is history
        write(root, "notes.md", "lab-a\n")
        paths_ = [rel for rel, _n in rename.plan(root, self.load(root), "lab-a", "lab-d")]
        self.assertIn("docs/sub/RETRO-LOG.md", paths_)
        for left_out in (".claude/skills/brain-sample/SKILL.md", "_meta/note.txt", "tests/test_x.py",
                         "docs/RETRO-LOG.md", "notes.md"):
            self.assertNotIn(left_out, paths_)

    def test_template_role_also_reaches_shipped_skills_and_meta_files(self):
        root = self.bare(role="template", prefix="template", skills=[
            ("template-a", "Plain.\n"), ("brain-retro", "Plain.\n"), ("brain-sample", "Hands to brain-retro.\n")])
        write(root, "_meta/ROUTING-META.md", "# Meta map\n\n" + FENCE + "mermaid\nflowchart LR\n"
              "brain-sample:::work --> brain-retro:::work\n" + FENCE + "\n")
        write(root, "_meta/gates.json",
              '{"rules": [{"path": "docs/x", "skills": ["brain-retro"], "why": "w"}], "exempt": []}\n')
        paths_ = dict(rename.plan(root, self.load(root), "brain-retro", "brain-review"))
        self.assertIn("_meta/ROUTING-META.md", paths_)
        self.assertIn("_meta/gates.json", paths_)
        self.assertIn(".claude/skills/brain-sample/SKILL.md", paths_)
        rename.apply(root, self.load(root), "brain-retro", "brain-review")
        self.assertIn('"skills": ["brain-review"]', read(root, "_meta/gates.json"))
        self.assertIn("brain-sample:::work --> brain-review:::work", read(root, "_meta/ROUTING-META.md"))
        self.assertTrue((root / ".claude/skills/brain-review/SKILL.md").is_file())

    def test_binary_symlinked_and_nested_repo_files_are_left_alone(self):
        root = self.brain()
        outside = self.tmp / "outside.md"
        outside.write_text("lab-a\n", encoding="utf-8")
        (root / "docs" / "link.md").symlink_to(outside)
        blob = root / "docs" / "blob.bin"
        blob.write_bytes(b"\x00\x01 lab-a \x02")
        (root / "docs" / "project" / ".git").mkdir(parents=True)
        write(root, "docs/project/notes.md", "lab-a\n")
        paths_ = [rel for rel, _n in rename.plan(root, self.load(root), "lab-a", "lab-d")]
        for left_out in ("docs/link.md", "docs/blob.bin", "docs/project/notes.md"):
            self.assertNotIn(left_out, paths_)
        rename.apply(root, self.load(root), "lab-a", "lab-d")
        self.assertEqual(outside.read_text(encoding="utf-8"), "lab-a\n")
        self.assertEqual(blob.read_bytes(), b"\x00\x01 lab-a \x02")
        self.assertEqual(read(root, "docs/project/notes.md"), "lab-a\n")

    def test_a_symlink_never_carries_a_rewrite_to_a_file_out_of_scope(self):
        root = self.brain()
        write(root, "_meta/note.txt", "lab-a\n")                      # inside the brain, but not in scope
        (root / "docs" / "alias.md").symlink_to(root / "_meta" / "note.txt")
        paths_ = [rel for rel, _n in rename.plan(root, self.load(root), "lab-a", "lab-d")]
        self.assertNotIn("docs/alias.md", paths_)
        rename.apply(root, self.load(root), "lab-a", "lab-d")
        self.assertEqual(read(root, "_meta/note.txt"), "lab-a\n")

    def test_a_scope_folder_that_points_outside_the_brain_is_not_written(self):
        root = self.brain()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "notes.md").write_text("lab-a\n", encoding="utf-8")
        shutil.rmtree(str(root / "scripts"))
        (root / "scripts").symlink_to(elsewhere, target_is_directory=True)
        paths_ = [rel for rel, _n in rename.plan(root, self.load(root), "lab-a", "lab-d")]
        self.assertNotIn("scripts/notes.md", paths_)
        rename.apply(root, self.load(root), "lab-a", "lab-d")
        self.assertEqual((elsewhere / "notes.md").read_text(encoding="utf-8"), "lab-a\n")

    def test_other_encodings_and_line_endings_survive(self):
        root = self.brain()
        (root / "docs" / "latin1.txt").write_bytes(b"caf\xe9 lab-a\r\nsecond line\r\n")
        write(root, "docs/bom.md", "﻿lab-a\n")
        rename.apply(root, self.load(root), "lab-a", "lab-d")
        self.assertEqual((root / "docs" / "latin1.txt").read_bytes(), b"caf\xe9 lab-d\r\nsecond line\r\n")
        self.assertEqual((root / "docs" / "bom.md").read_bytes(), "﻿lab-d\n".encode("utf-8"))


class ApplyTest(RenameCase):
    def test_apply_rewrites_everywhere(self):
        root = self.brain()
        retro = (root / "docs" / "RETRO-LOG.md").read_bytes()
        readme = self.snapshot(root)["README.md"]
        plan = rename.plan(root, self.load(root), "lab-a", "lab-d")
        self.assertEqual(dict(plan), {
            ".claude/skills/lab-a/SKILL.md": 2,   # its name, and its body's mention of itself
            ".claude/skills/lab-a/references/notes.md": 1,
            ".claude/skills/lab-ab/SKILL.md": 1,
            ".claude/skills/lab-c/SKILL.md": 1,
            ".claude/skills/lab-router/SKILL.md": 1,
            ".claude/skills/lab-router/rules.json": 3,   # skill, why, expect
            "CLAUDE.md": 1,
            "brain.json": 3,
            "docs/NOTES.md": 1,
            "docs/ROUTING.md": 2,
            "scripts/run.py": 1,
        })

        problems = []
        self.assertIsNone(rename.apply(root, self.load(root), "lab-a", "lab-d", problems))
        self.assertEqual(problems, [])

        # the folder moved and its frontmatter name followed
        self.assertFalse((root / ".claude/skills/lab-a").exists())
        self.assertIn("name: lab-d\n", read(root, ".claude/skills/lab-d/SKILL.md"))
        self.assertEqual(read(root, ".claude/skills/lab-d/references/notes.md"), "See lab-d for the details.\n")
        # other skills, the brain's docs and scripts
        self.assertIn("hands on to lab-d and to lab-ab", read(root, ".claude/skills/lab-router/SKILL.md"))
        self.assertEqual(read(root, "CLAUDE.md"), OLD_CLAUDE_MD.replace("`lab-a`", "`lab-d`"))
        self.assertEqual(read(root, "docs/NOTES.md"), "Mentions `lab-d` once and lab-ab once.\n")
        self.assertEqual(read(root, "scripts/run.py"), "# called by lab-d\nprint('hi')\n")
        # ROUTING.md node ids, with lab-ab left as it was
        routing_map = read(root, "docs/ROUTING.md")
        self.assertIn("lab-router --> lab-d:::work", routing_map)
        self.assertIn("lab-d --> lab-c:::work", routing_map)
        self.assertIn("lab-router --> lab-ab:::work", routing_map)
        self.assertNotIn("lab-a:::", routing_map)
        # rules.json: the skill and the expected answer, still valid JSON
        rules = json.loads(read(root, ".claude/skills/lab-router/rules.json"))
        self.assertEqual(rules["rules"][0]["skill"], "lab-d")
        self.assertEqual(rules["cases"][0]["expect"], "lab-d")
        self.assertEqual(rules["default"], "lab-ab")
        # brain.json: the gates changed and the file's own layout did not
        self.assertEqual(read(root, "brain.json"), BRAIN_JSON.replace('"lab-a"', '"lab-d"')
                         .replace("lab-a writes", "lab-d writes").replace("skills/lab-a/", "skills/lab-d/"))
        self.assertEqual(config.load(root).gates[0]["skills"], ["lab-d", "lab-ab"])
        # history and untouched files are byte for byte what they were
        self.assertEqual((root / "docs" / "RETRO-LOG.md").read_bytes(), retro)
        self.assertEqual(self.snapshot(root)["README.md"], readme)

    def test_where_blocks_are_regenerated(self):
        root = self.brain()
        rename.apply(root, self.load(root), "lab-a", "lab-d")
        self.assertIn("`lab-ab` · `lab-d`", self.block_of(root, "lab-c"))   # the order is sorted anew
        self.assertIn("**Reserved output:** writing `docs/notes/**`", self.block_of(root, "lab-d"))
        self.assertEqual(routing_sync.sync(root, self.load(root), check=True), [])  # nothing is out of date

    def test_nothing_else_is_rewritten(self):
        root = self.brain()
        before = self.snapshot(root)
        rename.apply(root, self.load(root), "lab-a", "lab-d")
        after = self.snapshot(root)
        for untouched in ("README.md", "docs/RETRO-LOG.md", "_meta/brain"):
            self.assertEqual(after[untouched], before[untouched], untouched)

    def test_plain_rename_when_the_folder_is_not_in_git(self):
        root = self.brain()
        self.git(root, "init", "-q")
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", "start")
        self.make_skill(root, "lab-fresh", "Does X. Use when Y.", BODY)   # never added
        r = self.run_brain(root, "rename-skill", "lab-fresh", "lab-new", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((root / ".claude/skills/lab-new/SKILL.md").is_file())
        self.assertIn("?? .claude/skills/lab-new/", self.git(root, "status", "--porcelain"))

    def test_tracked_folder_is_moved_with_git_mv(self):
        root = self.brain()
        self.git(root, "init", "-q")
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", "start")
        r = self.run_brain(root, "rename-skill", "lab-a", "lab-d", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        staged = self.git(root, "diff", "--cached", "--name-status", "-M")
        self.assertIn("R100\t.claude/skills/lab-a/SKILL.md\t.claude/skills/lab-d/SKILL.md", staged)
        self.assertIn("name: lab-d\n", read(root, ".claude/skills/lab-d/SKILL.md"))
        self.assertFalse((root / ".claude/skills/lab-a").exists())

    def test_cli_apply_reports_and_the_result_lints_clean(self):
        root = self.brain()
        r = self.run_brain(root, "rename-skill", "lab-a", "lab-d", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(".claude/skills/lab-d", r.stdout)
        self.assertIn("docs/ROUTING.md", r.stdout)
        self.assertNotIn("BROKEN", self.run_brain(root, "lint").stdout)

    def test_sync_refusals_are_reported_not_hidden(self):
        unclosed = "\n" + routing_sync.BEGIN + "\nno end marker\n"
        root = self.brain()
        write(root, ".claude/skills/lab-c/SKILL.md", read(root, ".claude/skills/lab-c/SKILL.md") + unclosed)
        problems = []
        rename.apply(root, self.load(root), "lab-a", "lab-d", problems)   # the rename itself is done
        self.assertTrue((root / ".claude/skills/lab-d/SKILL.md").is_file())
        self.assertEqual([f.severity for f in problems], [BROKEN])
        self.assertTrue(problems[0].subject.startswith(".claude/skills/lab-c/SKILL.md"), problems)

        other = self.brain()
        write(other, ".claude/skills/lab-c/SKILL.md", read(other, ".claude/skills/lab-c/SKILL.md") + unclosed)
        with self.assertRaises(routing_sync.SyncRefused):    # no list given: it cannot be missed
            rename.apply(other, self.load(other), "lab-a", "lab-d")
        self.assertTrue((other / ".claude/skills/lab-d/SKILL.md").is_file())

        third = self.brain()
        write(third, ".claude/skills/lab-c/SKILL.md", read(third, ".claude/skills/lab-c/SKILL.md") + unclosed)
        r = self.run_brain(third, "rename-skill", "lab-a", "lab-d", "--apply")
        self.assertEqual(r.returncode, 1)
        self.assertIn("BROKEN .claude/skills/lab-c/SKILL.md", r.stdout)
        self.assertIn("renamed lab-a to lab-d, but routing sync", r.stdout)   # and it says the rename is done
        self.assertTrue((third / ".claude/skills/lab-d/SKILL.md").is_file())


class RefusalTest(RenameCase):
    def assert_refused(self, root, old, new, fragment):
        before = self.snapshot(root)
        with self.assertRaises(rename.RenameError) as caught:
            rename.plan(root, self.load(root), old, new)
        self.assertIn(fragment, str(caught.exception))
        with self.assertRaises(rename.RenameError):
            rename.apply(root, self.load(root), old, new)
        r = self.run_brain(root, "rename-skill", old, new, "--apply")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn(fragment, r.stderr)
        self.assertEqual(self.snapshot(root), before)   # nothing moved, nothing rewritten

    def test_refusals(self):
        root = self.brain(extra_skills=[("brain-write-skill", "Plain.\n")])
        self.assert_refused(root, "brain-write-skill", "lab-w", "template")   # a brain cannot rename a shipped skill
        self.assert_refused(root, "lab-a", "lab-ab", "already exists")        # NEW is taken
        self.assert_refused(root, "lab-a", "other-a", "must start with 'lab-'")   # NEW without this brain's prefix
        self.assert_refused(root, "lab-a", "brain-a", "must start with 'lab-'")   # nor a shipped name
        self.assert_refused(root, "lab-a", "lab", "must start with 'lab-'")       # a prefix and nothing else
        self.assert_refused(root, "lab-a", "lab-Big", "NEW")                  # not a skill name
        self.assert_refused(root, "lab-a", "lab-a", "same")                   # a no-op
        self.assert_refused(root, "lab-zzz", "lab-y", "no skill")             # OLD does not exist
        self.assert_refused(root, "../x", "lab-y", "OLD")                     # nor reach out of the skills folder

    def test_unwritable_file_is_refused_before_anything_moves(self):
        if os.geteuid() == 0:
            self.skipTest("root can write anything")
        root = self.brain()
        path = root / "docs" / "NOTES.md"
        path.chmod(0o444)
        self.addCleanup(path.chmod, 0o644)
        before = self.snapshot(root)
        with self.assertRaises(rename.RenameError) as caught:
            rename.apply(root, self.load(root), "lab-a", "lab-d")
        self.assertIn("docs/NOTES.md", str(caught.exception))
        self.assertEqual(self.snapshot(root), before)

    def test_the_template_may_rename_a_shipped_skill_but_only_to_its_own_prefixes(self):
        root = self.bare(role="template", prefix="template",
                         skills=[("brain-sample", "Plain.\n"), ("template-a", "Plain.\n")])
        plan = rename.plan(root, self.load(root), "brain-sample", "brain-other")
        self.assertEqual([rel for rel, _n in plan], [".claude/skills/brain-sample/SKILL.md"])
        with self.assertRaises(rename.RenameError):
            rename.plan(root, self.load(root), "template-a", "lab-a")


if __name__ == "__main__":
    unittest.main()
