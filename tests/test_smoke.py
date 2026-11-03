"""Smoke tests: each route a person takes through the template, once, end to end.

`new`, `adopt` and `init` make a healthy brain; the gate and the pre-commit guard work in it; `update` brings
a change in; the template itself is healthy. Each test builds what it needs in a temporary folder whose path
contains a space (see helpers.py). Anything more detailed belongs in a test of the script that needs it.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest

from tests.helpers import TEMPLATE_ROOT, TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import managed

# A credential-shaped value, built at run time: no source file may hold one, because the template's own
# pre-commit guard scans every file it commits.
CREDENTIAL = "gh" + "p_" + "a" * 36
ENV_VALUE = "plain-value-" + "99"  # not credential-shaped: only the file name gives `.env` away

SKILL_PATH = ".claude/skills/se2-idea/SKILL.md"
SKILL = ("---\nname: se2-idea\ndescription: Captures an idea. Use when the person has one.\n---\n"
         "Write the idea down.\n")
NOTES = "existing notes\n"


def skill_names(root, prefix):
    return sorted(p.name for p in (root / ".claude" / "skills").glob(prefix + "*") if p.is_dir())


class SmokeTest(TempDirCase):
    # -- helpers ----------------------------------------------------------

    def new(self, template, dest, *extra):
        return self.run_brain(template, "new", str(dest), "--name", "homelab", "--prefix", "lab", *extra)

    def commit(self, root, message="a change"):
        """`git commit` in `root`, so the pre-commit guard runs; the result, whatever the exit code."""
        return subprocess.run(["git", "commit", "-q", "-m", message], cwd=str(root), env=self.env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL)

    def hook_input(self, root, tool, **tool_input):
        event = "PostToolUse" if tool == "Skill" else "PreToolUse"
        return json.dumps({"session_id": "smoke", "cwd": str(root), "hook_event_name": event,
                           "tool_name": tool, "tool_input": tool_input})

    def check_write(self, brain, rel):
        return self.run_brain(brain, "gate", "check", stdin=self.hook_input(brain, "Write", file_path=str(brain / rel)))

    # -- new --------------------------------------------------------------

    def test_new_makes_a_healthy_brain(self):
        brain = self.make_brain()
        doctor = self.run_brain(brain, "doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        shipped = skill_names(TEMPLATE_ROOT, "brain-")
        self.assertTrue(shipped)
        self.assertEqual(skill_names(brain, "brain-"), shipped)
        self.assertEqual(skill_names(brain, "template-"), [])
        self.assertFalse((brain / "tests").exists())
        tracked = self.git(brain, "ls-files").split()
        self.assertIn(".mcp.json", tracked)
        self.assertIn("docs/GLOSSARY.md", tracked)
        brief = self.run_brain(brain, "doctor", "--brief")
        self.assertEqual(brief.returncode, 0, brief.stdout + brief.stderr)
        self.assertNotIn("ok ", brief.stdout)  # only what needs attention

    def test_new_dry_run_writes_nothing(self):
        template = self.copy_template()
        dest = self.tmp / "my brain"
        dry = self.new(template, dest, "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertFalse(dest.exists())

    def test_the_gate_refuses_a_skill_file_until_brain_write_skill_is_recorded(self):
        brain = self.make_brain()
        target = ".claude/skills/lab-x/SKILL.md"
        refused = self.check_write(brain, target)
        self.assertEqual(refused.returncode, 0, refused.stderr)  # a gate command never fails the tool call
        answer = json.loads(refused.stdout)["hookSpecificOutput"]
        self.assertEqual(answer["permissionDecision"], "deny")
        self.assertIn("brain-write-skill", answer["permissionDecisionReason"])
        recorded = self.run_brain(brain, "gate", "record",
                                  stdin=self.hook_input(brain, "Skill", skill="brain-write-skill"))
        self.assertEqual((recorded.returncode, recorded.stdout, recorded.stderr), (0, "", ""))
        allowed = self.check_write(brain, target)
        self.assertEqual((allowed.returncode, allowed.stdout, allowed.stderr), (0, "", ""))
        usage = self.run_brain(brain, "usage")
        self.assertRegex(usage.stdout, r"brain-write-skill\s+1\s+last ")

    def test_hook_self_test_passes(self):
        brain = self.make_brain()
        selftest = self.run_brain(brain, "hook", "self-test")
        self.assertEqual(selftest.returncode, 0, selftest.stdout + selftest.stderr)

    def test_the_guard_refuses_a_credential_and_an_env_file(self):
        brain = self.make_brain()
        before = self.git(brain, "rev-parse", "HEAD")

        (brain / "docs" / "note.md").write_text("key " + CREDENTIAL + "\n", encoding="utf-8")
        self.git(brain, "add", "docs/note.md")
        refused = self.commit(brain)
        self.assertNotEqual(refused.returncode, 0, refused.stdout + refused.stderr)
        self.assertIn("BLOCK  github-token: docs/note.md", refused.stdout + refused.stderr)
        self.assertNotIn(CREDENTIAL, refused.stdout + refused.stderr)
        self.assertEqual(self.git(brain, "rev-parse", "HEAD"), before)
        self.git(brain, "reset", "-q")

        (brain / ".env").write_text("NOTE=" + ENV_VALUE + "\n", encoding="utf-8")
        self.git(brain, "add", "-f", ".env")  # -f: the managed .gitignore keeps it out of a plain add
        refused = self.commit(brain)
        self.assertNotEqual(refused.returncode, 0, refused.stdout + refused.stderr)
        self.assertIn("BLOCK  env-file: .env", refused.stdout + refused.stderr)
        self.assertNotIn(ENV_VALUE, refused.stdout + refused.stderr)
        self.assertEqual(self.git(brain, "rev-parse", "HEAD"), before)

    def test_secret_run_hands_values_to_the_command_and_prints_none(self):
        brain = self.make_brain()
        (brain / ".env").write_text(f"LAB_PLAIN={ENV_VALUE}\nLAB_REF=op://vault/item/field\n", encoding="utf-8")
        tools = self.tmp / "fake tools"
        tools.mkdir()
        op = tools / "op"  # stands in for 1Password's CLI
        op.write_text('#!/bin/sh\n[ "$3" = "op://vault/item/field" ] && printf "%s" "from-op-' + "7" * 8 + '"\n',
                      encoding="utf-8")
        op.chmod(0o755)
        self.env = {**self.env, "PATH": f"{tools}{os.pathsep}{self.env.get('PATH', '')}"}
        child = ("import os, sys; ok = os.environ['LAB_PLAIN'] == sys.argv[1] and "
                 "os.environ['LAB_REF'] == 'from-op-' + '7' * 8; print('match' if ok else 'differ')")
        ran = self.run_brain(brain, "secret", "run", "LAB_PLAIN,LAB_REF", "python3", "-c", child, ENV_VALUE)
        self.assertEqual((ran.returncode, ran.stdout.strip()), (0, "match"), ran.stderr)
        missing = self.run_brain(brain, "secret", "run", "LAB_ABSENT", "true")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("LAB_ABSENT is not set", missing.stderr)
        self.assertNotIn(ENV_VALUE, missing.stdout + missing.stderr)

    # -- adopt ------------------------------------------------------------

    def test_adopt_keeps_the_persons_files_and_the_first_commit_goes_through(self):
        template = self.copy_template()
        ws = self.tmp / "my workspace"
        (ws / ".claude" / "skills" / "se2-idea").mkdir(parents=True)
        (ws / SKILL_PATH).write_text(SKILL, encoding="utf-8")
        (ws / "CLAUDE.md").write_text(NOTES, encoding="utf-8")
        args = ["adopt", str(ws), "--name", "workspace", "--prefix", "se2", "--description", "My workspace"]

        before_ws, before_template = self.snapshot(ws), self.snapshot(template)
        dry = self.run_brain(template, *args, "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertEqual(self.snapshot(ws), before_ws)
        self.assertEqual(self.snapshot(template), before_template)

        real = self.run_brain(template, *args)
        self.assertEqual(real.returncode, 0, real.stdout + real.stderr)
        self.assertEqual((ws / SKILL_PATH).read_text(encoding="utf-8"), SKILL)
        claude_md = (ws / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(claude_md.startswith(managed.MD_BEGIN + "\n"))
        self.assertTrue(claude_md.endswith(managed.MD_END + "\n\n" + NOTES), claude_md)

        # adopt makes no commit; the person's first one has to get through the guard
        self.git(ws, "add", "-A")
        first = self.commit(ws, "first commit")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

    # -- init -------------------------------------------------------------

    def test_init_turns_a_plain_clone_into_a_brain_with_a_fresh_history(self):
        template = self.copy_template(with_local=False)
        clone = self._new_dir("clone")
        self.git(self.tmp, "clone", "-q", str(template), str(clone))
        done = self.run_brain(clone, "init", "--name", "homelab", "--prefix", "lab")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

        self.assertFalse((clone / "tests").exists())
        self.assertFalse((clone / "docs" / "superpowers").exists())
        self.assertEqual(skill_names(clone, "template-"), [])
        self.assertTrue(skill_names(clone, "brain-"))
        doctor = self.run_brain(clone, "doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        subjects = self.git(clone, "log", "--all", "--format=%s").splitlines()
        self.assertEqual(len(subjects), 1, subjects)
        self.assertTrue(subjects[0].startswith("meta(brain): initialise from template v"), subjects)

    # -- update -----------------------------------------------------------

    def test_update_brings_in_a_committed_change_to_a_shipped_skill(self):
        template = self.copy_template()
        brain = self.tmp / "my brain"
        made = self.new(template, brain)
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)

        skill = ".claude/skills/brain-sync/SKILL.md"
        changed = (template / skill).read_text(encoding="utf-8") + "\nChanged by the template.\n"
        (template / skill).write_text(changed, encoding="utf-8")
        self.git(template, "add", "-A")
        self.git(template, "commit", "-q", "-m", "skill(brain-sync): a change")

        updated = self.run_brain(brain, "update")
        self.assertEqual(updated.returncode, 0, updated.stdout + updated.stderr)
        self.assertEqual((brain / skill).read_text(encoding="utf-8"), changed)
        doctor = self.run_brain(brain, "doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)

    # -- the template itself ----------------------------------------------

    def test_the_template_is_healthy(self):
        template = self.copy_template(with_local=True)  # a copy with local/ and the pre-commit hook
        doctor = self.run_brain(template, "doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        lint = self.run_brain(template, "lint")
        self.assertEqual(lint.stdout.strip().splitlines()[-1], "lint: 0 broken, 0 gap, 0 orphan", lint.stdout)
        synced = self.run_brain(template, "routing", "sync", "--check")
        self.assertEqual(synced.returncode, 0, synced.stdout + synced.stderr)

    def test_the_templates_settings_are_the_managed_ones(self):
        written = json.loads((TEMPLATE_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(written, managed.merge_settings({}))


if __name__ == "__main__":
    unittest.main()
