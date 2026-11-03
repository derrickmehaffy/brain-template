from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from tests.helpers import TEMPLATE_ROOT, TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config, gate, lint
from brainlib.report import BROKEN, Finding
from brainlib.skills import list_skills

ROUTING_WHY = "The routing map changes when a skill is placed, through brain-write-skill."
DRAFT_RULE = {"path": "out/*.md", "skills": ["lab-draft"], "spend_on_revision": True,
              "why": "Drafts are reviewed again on every revision."}


def refusal(rel, skills, why, waive_skill=None):
    """The exact `permissionDecisionReason` for a refused write (pinned by the brief)."""
    needs = skills[0] + (f" (or {' or '.join(skills[1:])})" if len(skills) > 1 else "")
    return (f"skill gate: writing {rel} needs {needs} to run first in this session. {why} "
            f"Invoke the skill; a one-time waiver needs the person's express say-so: "
            f"_meta/brain gate waive {waive_skill or skills[0]} \"<reason, and who said so>\"")


class GateCase(TempDirCase):
    """Drives `_meta/brain gate check|record` with payloads shaped like Claude Code's hook input."""

    # -- running the hooks -------------------------------------------------------

    def hook_raw(self, root, action, stdin):
        r = self.run_brain(root, "gate", action, stdin=stdin)
        self.assertEqual(r.returncode, 0, r.stderr)  # a gate command never fails the tool call
        self.assertNotIn('"allow"', r.stdout)  # and never bypasses the person's permission prompt
        return r

    def hook(self, root, action, tool, session="s1", cwd=None, **tool_input):
        body = {"session_id": session, "cwd": str(cwd if cwd is not None else root),
                "hook_event_name": "PreToolUse" if action == "check" else "PostToolUse",
                "tool_name": tool, "tool_input": tool_input}
        return self.hook_raw(root, action, json.dumps(body))

    def write(self, root, rel, session="s1", tool="Write"):
        return self.hook(root, "check", tool, session=session, file_path=str(Path(root) / rel))

    def bash(self, root, command, session="s1"):
        return self.hook(root, "check", "Bash", session=session, command=command)

    def ran(self, root, skill, session="s1"):
        r = self.hook(root, "record", "Skill", session=session, skill=skill)
        self.assertEqual((r.stdout, r.stderr), ("", ""))

    def waive(self, root, skill, reason):
        r = self.run_brain(root, "gate", "waive", skill, reason)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def status(self, root, *args):
        r = self.run_brain(root, "gate", "status", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    # -- reading the answers -----------------------------------------------------

    def assert_silent(self, r):
        self.assertEqual((r.stdout, r.stderr), ("", ""))

    def denied(self, r):
        """The reason of a refusal; the whole output has exactly the pinned shape."""
        out = json.loads(r.stdout)
        self.assertEqual(list(out), ["hookSpecificOutput"])
        inner = out["hookSpecificOutput"]
        self.assertEqual(sorted(inner), ["hookEventName", "permissionDecision", "permissionDecisionReason"])
        self.assertEqual((inner["hookEventName"], inner["permissionDecision"]), ("PreToolUse", "deny"))
        return inner["permissionDecisionReason"]

    def notice(self, r):
        """The message of a notice: a `systemMessage` and nothing else."""
        out = json.loads(r.stdout)
        self.assertEqual(list(out), ["systemMessage"])
        return out["systemMessage"]

    # -- builders ----------------------------------------------------------------

    def draft_brain(self):
        return self.fake_brain(extra={"gates": [dict(DRAFT_RULE)]})

    def state_dir(self, root):
        digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
        return Path(self.env["TMPDIR"]) / "brain-gate" / digest

    def waiver_path(self, root):
        return Path(root) / ".brain" / "gate-waiver.json"

    def waiver_log(self, root):
        text = (Path(root) / ".brain" / "gate-waivers.log").read_text(encoding="utf-8")
        return [line.split("\t") for line in text.splitlines()]


class SkillGateTest(GateCase):
    def test_unruled_path_passes_silently(self):
        root = self.fake_brain()
        for rel in ("notes/today.md", "README.md", "docs/other.md", "scriptsfoo/x.py", ".claude/settings.json"):
            with self.subTest(rel=rel):
                self.assert_silent(self.write(root, rel))

    def test_ruled_path_refused_until_recorded(self):
        root = self.fake_brain()
        r = self.write(root, "docs/ROUTING.md")
        self.assertEqual(json.loads(r.stdout), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": refusal("docs/ROUTING.md", ["brain-write-skill"], ROUTING_WHY)}})
        self.assertIn("brain-write-skill", self.denied(r))
        self.assertIn(ROUTING_WHY, self.denied(r))
        self.ran(root, "brain-write-skill")
        self.assert_silent(self.write(root, "docs/ROUTING.md"))
        self.assert_silent(self.write(root, "docs/ROUTING.md", tool="Edit"))
        # The run belongs to its session: another session is still refused.
        self.denied(self.write(root, "docs/ROUTING.md", session="s2"))

    def test_any_owning_skill_opens_a_rule_and_the_refusal_names_the_alternative(self):
        root = self.fake_brain()
        reason = self.denied(self.write(root, "docs/UPSTREAM.md"))
        self.assertTrue(reason.startswith(
            "skill gate: writing docs/UPSTREAM.md needs brain-upstream (or brain-sync) to run first in this session. "))
        self.ran(root, "brain-sync")
        self.assert_silent(self.write(root, "docs/UPSTREAM.md"))

    def test_a_skill_that_owns_a_different_rule_does_not_open_this_one(self):
        root = self.fake_brain()
        self.ran(root, "brain-write-script")
        self.assert_silent(self.write(root, "scripts/a/b.py"))
        self.denied(self.write(root, "docs/ROUTING.md"))

    def test_every_shipped_rule_refuses_its_path(self):
        root = self.fake_brain()
        cases = {
            "docs/ROUTING.md": "brain-write-skill", "scripts/deploy.py": "brain-write-script",
            "scripts/a/b/c.sh": "brain-write-script", "docs/CAPABILITIES.md": "brain-write-script",
            "docs/practices/p.md": "brain-write-practice", "docs/practices/sub/p.md": "brain-write-practice",
            "docs/RETRO-LOG.md": "brain-retro", "docs/UNCLASSIFIED-LOG.md": "brain-retro",
            "docs/UPSTREAM.md": "brain-upstream", ".claude/skills/lab-x/SKILL.md": "brain-write-skill",
            ".claude/skills/lab-x/references/r.md": "brain-write-skill",
        }
        for rel, skill in cases.items():
            with self.subTest(rel=rel):
                self.assertIn(f"needs {skill}", self.denied(self.write(root, rel)))

    def test_shipped_rule_refuses_new_skill_file(self):
        root = self.fake_brain()
        reason = self.denied(self.write(root, ".claude/skills/lab-new/SKILL.md"))
        self.assertIn("brain-write-skill", reason)
        self.assertIn("Skills are written through brain-write-skill", reason)
        self.assert_silent(self.write(root, ".claude/skills/other-new/SKILL.md"))  # not this brain's prefix
        self.ran(root, "brain-write-skill")
        self.assert_silent(self.write(root, ".claude/skills/lab-new/SKILL.md"))

    def test_only_in_template_rule(self):
        template = self.fake_brain(prefix="template", role="template")
        self.assertIn("needs brain-write-skill", self.denied(self.write(template, ".claude/skills/brain-x/SKILL.md")))
        self.assertIn("needs brain-write-skill", self.denied(self.write(template, ".claude/skills/template-y/SKILL.md")))
        brain = self.fake_brain()
        self.assert_silent(self.write(brain, ".claude/skills/brain-x/SKILL.md"))  # template-owned in a brain
        self.denied(self.write(brain, ".claude/skills/lab-x/SKILL.md"))

    def test_brain_rules_come_from_brain_json(self):
        root = self.draft_brain()
        self.assertIn(DRAFT_RULE["why"], self.denied(self.write(root, "out/a.md")))
        self.assert_silent(self.write(root, "out/sub/a.md"))  # * does not cross /
        self.assert_silent(self.write(root, "out/a.txt"))
        self.ran(root, "lab-draft")
        self.assert_silent(self.write(root, "out/a.md"))

    def test_spend_on_revision(self):
        root = self.draft_brain()
        self.denied(self.write(root, "out/a.md"))  # creating a file still needs the skill to have run
        self.ran(root, "lab-draft")
        # Creating costs nothing: it can be done again and the run is still there.
        self.assert_silent(self.write(root, "out/a.md"))
        self.assert_silent(self.write(root, "out/b.md"))
        self.assertIn("lab-draft x1", self.status(root, "--session", "s1")[1])
        # Once the file exists, an edit passes with a notice and spends the run ...
        (root / "out").mkdir()
        (root / "out" / "a.md").write_text("draft\n", encoding="utf-8")
        message = self.notice(self.write(root, "out/a.md", tool="Edit"))
        self.assertIn("lab-draft", message)
        self.assertIn("out/a.md", message)
        self.assertIn("lab-draft x0", self.status(root, "--session", "s1")[1])
        # ... so the next edit is refused until the skill runs again.
        self.assertIn("needs lab-draft", self.denied(self.write(root, "out/a.md", tool="Edit")))
        self.ran(root, "lab-draft")
        self.notice(self.write(root, "out/a.md", tool="Edit"))
        self.denied(self.write(root, "out/a.md", tool="Edit"))

    def test_without_spend_on_revision_one_run_covers_every_edit(self):
        root = self.fake_brain()
        self.ran(root, "brain-write-skill")
        (root / "docs").mkdir()
        (root / "docs" / "ROUTING.md").write_text("map\n", encoding="utf-8")
        for _ in range(3):
            self.assert_silent(self.write(root, "docs/ROUTING.md", tool="Edit"))

    def test_waiver_one_shot_logged_announced(self):
        root = self.fake_brain()
        r = self.waive(root, "brain-write-skill", "Dana said so in chat")
        self.assertIn("brain-write-skill", r.stdout)
        self.assertTrue(self.waiver_path(root).exists())
        message = self.notice(self.write(root, "docs/ROUTING.md"))
        self.assertIn("waiver", message)
        self.assertIn("brain-write-skill", message)
        self.assertIn("docs/ROUTING.md", message)
        self.assertFalse(self.waiver_path(root).exists())  # consumed
        self.assertIn("needs brain-write-skill", self.denied(self.write(root, "docs/ROUTING.md")))
        armed, used = self.waiver_log(root)
        self.assertEqual(armed[1:], ["armed", "brain-write-skill", "Dana said so in chat", ""])
        self.assertEqual(used[1:], ["used", "brain-write-skill", "Dana said so in chat", "docs/ROUTING.md"])
        for fields in (armed, used):
            self.assertEqual(len(fields), 5)
            datetime.fromisoformat(fields[0])  # ISO time

    def test_waiver_for_another_skill_is_not_used_and_survives(self):
        root = self.fake_brain()
        self.waive(root, "brain-retro", "wrong skill")
        self.denied(self.write(root, "docs/ROUTING.md"))
        self.assertTrue(self.waiver_path(root).exists())
        self.notice(self.write(root, "docs/RETRO-LOG.md"))  # the owner it names
        self.assertFalse(self.waiver_path(root).exists())

    def test_waiver_is_not_spent_when_the_skill_already_ran(self):
        root = self.fake_brain()
        self.ran(root, "brain-write-skill")
        self.waive(root, "brain-write-skill", "belt and braces")
        self.assert_silent(self.write(root, "docs/ROUTING.md"))
        self.assertTrue(self.waiver_path(root).exists())

    def test_waiver_log_keeps_one_line_per_event(self):
        root = self.fake_brain()
        self.waive(root, "brain-retro", "two\nlines\tand a tab")
        self.notice(self.write(root, "docs/RETRO-LOG.md"))
        rows = self.waiver_log(root)
        self.assertEqual([len(row) for row in rows], [5, 5])
        self.assertEqual(rows[0][3], "two lines and a tab")

    def test_waive_needs_a_skill_and_a_reason(self):
        root = self.fake_brain()
        self.assertEqual(self.run_brain(root, "gate", "waive", "brain-retro").returncode, 2)
        r = self.run_brain(root, "gate", "waive", "brain-retro", "   ")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self.waiver_path(root).exists())

    def test_bash_targets_caught(self):
        root = self.fake_brain()
        commands = [
            ("echo x > docs/ROUTING.md", "docs/ROUTING.md"),
            ("echo x>docs/ROUTING.md", "docs/ROUTING.md"),
            ("cat a | tee -a scripts/x.py", "scripts/x.py"),
            ("cp a scripts/y.py", "scripts/y.py"),
            ("mv a docs/practices/p.md", "docs/practices/p.md"),
            ("sed -i '' -e s/a/b/ docs/CAPABILITIES.md", "docs/CAPABILITIES.md"),
            ('echo "x" >> "docs/RETRO-LOG.md"', "docs/RETRO-LOG.md"),
            ("ls && printf hi >| docs/UNCLASSIFIED-LOG.md", "docs/UNCLASSIFIED-LOG.md"),
            ("cd /tmp; cp a b\ncp c scripts/z.py", "scripts/z.py"),
            ("cat > .claude/skills/lab-q/SKILL.md <<EOF\nhi\nEOF", ".claude/skills/lab-q/SKILL.md"),
        ]
        for command, rel in commands:
            with self.subTest(command=command):
                self.assertIn(f"writing {rel} needs", self.denied(self.bash(root, command)))

    def test_bash_into_a_folder_that_exists_is_caught(self):
        root = self.fake_brain()
        (root / "scripts").mkdir()
        for command in ("cp a scripts/", "cp -r a b scripts", "mv a scripts", "cp -t scripts a"):
            with self.subTest(command=command):
                self.assertIn("needs brain-write-script", self.denied(self.bash(root, command)))

    def test_bash_passes_once_the_skill_ran(self):
        root = self.fake_brain()
        self.ran(root, "brain-write-script")
        self.assert_silent(self.bash(root, "cat a | tee -a scripts/x.py"))

    def test_bash_without_targets_passes(self):
        root = self.fake_brain()
        for command in ("ls -la", "git status", "_meta/brain lint", "", "echo hello world",
                        "cat docs/ROUTING.md", "sed -n 1,5p docs/ROUTING.md", "sed -e s/in/out/ docs/ROUTING.md",
                        "cp docs/ROUTING.md /tmp/copy.md", "echo hi 2>&1 | head", "ls docs/practices 2>/dev/null",
                        "grep -r 'a > b' scripts", "echo x > /dev/null", "cp a", "tee",
                        "git commit -m 'update docs/ROUTING.md'"):
            with self.subTest(command=command):
                self.assert_silent(self.bash(root, command))

    def test_gates_off_and_exempt(self):
        root = self.fake_brain(extra={
            "gates_off": [{"path": "docs/ROUTING.md", "why": "routing is hand-kept in this brain"}],
            "gate_exempt": ["scripts/archive/**"]})
        self.assert_silent(self.write(root, "docs/ROUTING.md"))  # turned off
        self.assert_silent(self.bash(root, "echo x > docs/ROUTING.md"))
        self.denied(self.write(root, "docs/CAPABILITIES.md"))  # the other shipped rules stay
        self.denied(self.write(root, "scripts/x.py"))
        self.assert_silent(self.write(root, "scripts/archive/old.py"))  # exempt
        self.assert_silent(self.bash(root, "cp a scripts/archive/old.py"))

    def test_gates_off_can_name_the_pattern_as_shipped(self):
        root = self.fake_brain(extra={
            "gates_off": [{"path": ".claude/skills/{prefix}-*/**", "why": "skills are free-form here"}]})
        self.assert_silent(self.write(root, ".claude/skills/lab-new/SKILL.md"))
        self.denied(self.write(root, "docs/ROUTING.md"))

    def test_gates_off_does_not_turn_off_the_brains_own_rules(self):
        root = self.fake_brain(extra={"gates": [dict(DRAFT_RULE)],
                                      "gates_off": [{"path": "out/*.md", "why": "only shipped rules can be turned off"}]})
        self.denied(self.write(root, "out/a.md"))

    def test_shipped_exempt_globs_are_never_checked(self):
        root = self.fake_brain()
        shipped = json.loads((root / "_meta" / "gates.json").read_text(encoding="utf-8"))
        shipped["exempt"] = ["docs/practices/archive/**"]
        (root / "_meta" / "gates.json").write_text(json.dumps(shipped), encoding="utf-8")
        self.assert_silent(self.write(root, "docs/practices/archive/old.md"))
        self.denied(self.write(root, "docs/practices/new.md"))

    def test_path_normalisation(self):
        root = self.fake_brain()
        self.denied(self.hook(root, "check", "Write", file_path=str(root / "scripts" / "x.py")))  # absolute, inside
        self.assert_silent(self.hook(root, "check", "Write", file_path="/etc/hosts"))
        self.denied(self.hook(root, "check", "Write", file_path="docs/../scripts/x.py"))  # relative to cwd
        self.denied(self.hook(root, "check", "Write", file_path=f"{root}//docs//ROUTING.md"))
        self.denied(self.hook(root, "check", "Write", file_path=f"{root}/docs/./practices/../ROUTING.md"))
        self.assert_silent(self.hook(root, "check", "Write", file_path=f"{root}/docs/../../elsewhere/scripts/x.py"))
        self.assert_silent(self.hook(root, "check", "Write", file_path=f"{root}-twin/scripts/x.py"))
        self.assert_silent(self.hook(root, "check", "Write", file_path=str(root)))
        # Relative paths resolve against the payload's cwd, not the hook's own.
        (root / "sub").mkdir()
        self.denied(self.hook(root, "check", "Write", cwd=root / "sub", file_path="../scripts/x.py"))
        self.assert_silent(self.hook(root, "check", "Write", cwd=root / "sub", file_path="scripts/x.py"))
        self.denied(self.hook(root, "check", "Bash", cwd=root / "sub", command="echo x > ../docs/ROUTING.md"))

    def test_paths_are_followed_through_symlinks(self):
        root = self.fake_brain()
        (root / "scripts").mkdir()
        (root / "shortcut").symlink_to(root / "scripts")
        alias = self.tmp / "alias"
        alias.symlink_to(root)
        outside = self.tmp / "outside"
        outside.mkdir()
        (root / "leak").symlink_to(outside)
        self.denied(self.write(root, "shortcut/x.py"))  # a link inside the brain to a ruled folder
        self.denied(self.hook(root, "check", "Write", file_path=str(alias / "docs" / "ROUTING.md")))  # the brain by another name
        self.assert_silent(self.write(root, "leak/scripts/x.py"))  # a link out of the brain

    def test_notebook_path_is_checked(self):
        root = self.fake_brain()
        r = self.hook(root, "check", "NotebookEdit", notebook_path=str(root / "scripts" / "n.ipynb"))
        self.assertIn("writing scripts/n.ipynb needs brain-write-script", self.denied(r))

    def test_malformed_payload_fails_open(self):
        root = self.fake_brain()
        for stdin in ("not json", "", "[]", '"text"', "{"):
            with self.subTest(stdin=stdin):
                r = self.hook_raw(root, "check", stdin)
                self.assertTrue(self.notice(r).startswith("skill gate error (write allowed): "))
        # Valid JSON with nothing to check passes without a word.
        for body in ({}, {"tool_name": "Write"}, {"tool_input": None}, {"tool_input": "oops"}, {"tool_input": []},
                     {"tool_input": {"file_path": 5}}, {"tool_input": {"file_path": ""}},
                     {"tool_input": {"command": ["scripts/x.py"]}}, {"tool_input": {}}):
            with self.subTest(body=body):
                self.assert_silent(self.hook_raw(root, "check", json.dumps(body)))

    def test_record_survives_a_malformed_payload_and_ignores_other_tools(self):
        root = self.fake_brain()
        r = self.hook_raw(root, "record", "not json")
        self.assertIn("skill gate error", self.notice(r))
        for body in ({}, {"tool_name": "Write", "tool_input": {"skill": "brain-write-skill"}},
                     {"tool_name": "Skill", "tool_input": {}}, {"tool_name": "Skill", "tool_input": {"skill": 7}},
                     {"tool_name": "Skill", "tool_input": {"skill": "  "}}):
            with self.subTest(body=body):
                self.assert_silent(self.hook_raw(root, "record", json.dumps(body)))
        self.denied(self.write(root, "docs/ROUTING.md"))  # nothing above counted as a run

    def test_an_internal_error_lets_the_write_through_with_a_warning(self):
        root = self.fake_brain()
        (root / "brain.json").write_text("{ not json", encoding="utf-8")
        message = self.notice(self.write(root, "docs/ROUTING.md"))
        self.assertTrue(message.startswith("skill gate error (write allowed): "))
        (root / "brain.json").write_text("{}", encoding="utf-8")
        (root / "_meta" / "gates.json").write_text("{ broken", encoding="utf-8")
        self.assertTrue(self.notice(self.write(root, "docs/ROUTING.md")).startswith("skill gate error (write allowed): "))

    def test_a_command_that_names_no_target_never_reads_the_config(self):
        # `gate check` runs on every tool call: with nothing to check it must not even load brain.json.
        root = self.fake_brain()
        (root / "brain.json").write_text("{ not json", encoding="utf-8")
        self.assert_silent(self.bash(root, "ls -la"))
        self.assert_silent(self.write(root, "../outside/x.py"))
        self.assert_silent(self.hook(root, "check", "Write", file_path="/etc/hosts"))

    def test_gate_check_stays_light(self):
        root = self.fake_brain()
        code = ("import json, sys; sys.path.insert(0, sys.argv[1]); from brainlib import gate; "
                "gate.check(sys.argv[2], {'tool_input': {'command': 'ls'}}); "
                "print(sorted(m for m in ('dataclasses', 'tempfile', 'hashlib', 'inspect', 'argparse') if m in sys.modules))")
        r = subprocess.run([sys.executable, "-c", code, str(root / "_meta"), str(root)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "[]")

    def test_never_emits_allow(self):
        root = self.draft_brain()
        (root / "out").mkdir()
        (root / "out" / "a.md").write_text("x", encoding="utf-8")
        outputs = [
            self.write(root, "notes/a.md"), self.write(root, "docs/ROUTING.md"), self.bash(root, "ls"),
            self.bash(root, "echo x > scripts/a.py"), self.hook_raw(root, "check", "not json"),
        ]
        self.ran(root, "lab-draft")
        outputs += [self.write(root, "out/a.md", tool="Edit")]
        self.waive(root, "brain-retro", "test")
        outputs += [self.write(root, "docs/RETRO-LOG.md")]
        for r in outputs:
            self.assertNotIn('"allow"', r.stdout)
            if r.stdout:
                out = json.loads(r.stdout)
                self.assertIn(set(out), ({"systemMessage"}, {"hookSpecificOutput"}))
                if "hookSpecificOutput" in out:
                    self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_session_ids_are_reduced_to_safe_characters(self):
        root = self.fake_brain()
        self.ran(root, "brain-write-skill", session="../../evil/x y")
        files = sorted(p.name for p in self.state_dir(root).iterdir())
        self.assertEqual(files, ["evilxy.json"])
        self.assertEqual(list(Path(self.env["TMPDIR"]).glob("*")), [self.state_dir(root).parent])
        self.assert_silent(self.write(root, "docs/ROUTING.md", session="../../evil/x y"))
        self.assert_silent(self.write(root, "docs/ROUTING.md", session="evilxy"))  # the same reduced id

    def test_a_payload_without_a_session_id_still_works(self):
        root = self.fake_brain()
        record = {"tool_name": "Skill", "tool_input": {"skill": "brain-write-skill"}}
        check = {"tool_name": "Write", "tool_input": {"file_path": str(root / "docs" / "ROUTING.md")}}
        self.denied(self.hook_raw(root, "check", json.dumps(check)))
        self.assert_silent(self.hook_raw(root, "record", json.dumps(record)))
        self.assert_silent(self.hook_raw(root, "check", json.dumps(check)))

    def test_state_file_layout(self):
        root = self.fake_brain()
        self.ran(root, "brain-write-skill")
        self.ran(root, "brain-write-skill")
        path = self.state_dir(root) / "s1.json"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"ran": {"brain-write-skill": 2}, "last_refusal": None})
        self.denied(self.write(root, "scripts/x.py"))
        state = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(state["ran"], {"brain-write-skill": 2})
        self.assertEqual({k: state["last_refusal"][k] for k in ("path", "skills")},
                         {"path": "scripts/x.py", "skills": ["brain-write-script"]})

    def test_a_corrupt_state_file_counts_as_nothing_ran(self):
        root = self.fake_brain()
        self.ran(root, "brain-write-skill")
        (self.state_dir(root) / "s1.json").write_text("garbage", encoding="utf-8")
        self.denied(self.write(root, "docs/ROUTING.md"))
        self.ran(root, "brain-write-skill")
        self.assert_silent(self.write(root, "docs/ROUTING.md"))

    def test_status(self):
        root = self.fake_brain()
        self.assertEqual(self.status(root, "--session", "s1"),
                         ["session: s1", "ran: nothing", "waiver: none", "last refusal: none"])
        self.ran(root, "brain-write-script")
        self.denied(self.write(root, "docs/ROUTING.md"))
        self.waive(root, "brain-retro", "Dana asked for it")
        lines = self.status(root, "--session", "s1")
        self.assertEqual(lines[0], "session: s1")
        self.assertEqual(lines[1], "ran: brain-write-script x1")
        self.assertTrue(lines[2].startswith("waiver: brain-retro armed "), lines[2])
        self.assertIn("Dana asked for it", lines[2])
        self.assertTrue(lines[3].startswith("last refusal: docs/ROUTING.md needs brain-write-skill"), lines[3])
        # A waiver once used is gone; the refusal stays.
        self.notice(self.write(root, "docs/RETRO-LOG.md"))
        lines = self.status(root, "--session", "s1")
        self.assertEqual(lines[2], "waiver: none")
        self.assertTrue(lines[3].startswith("last refusal: docs/ROUTING.md"))

    def test_status_without_a_session_reports_the_latest_one(self):
        root = self.fake_brain()
        self.assertEqual(self.status(root)[0], "session: none")
        self.ran(root, "brain-write-skill", session="old")
        old = self.state_dir(root) / "old.json"
        os.utime(str(old), (1, 1))
        self.ran(root, "brain-retro", session="new")
        lines = self.status(root)
        self.assertEqual(lines[:2], ["session: new", "ran: brain-retro x1"])
        self.assertEqual(self.status(root, "--session", "old")[1], "ran: brain-write-skill x1")

    def test_state_is_per_brain(self):
        first, second = self.fake_brain(), self.fake_brain()
        self.ran(first, "brain-write-skill")
        self.assert_silent(self.write(first, "docs/ROUTING.md"))
        self.denied(self.write(second, "docs/ROUTING.md"))


class GateFunctionsTest(GateCase):
    def test_bash_targets(self):
        cases = [
            ("echo x > docs/ROUTING.md", ["docs/ROUTING.md"]),
            ("echo x>docs/ROUTING.md", ["docs/ROUTING.md"]),
            ('echo "x" >> "docs/RETRO-LOG.md"', ["docs/RETRO-LOG.md"]),
            ("echo x >| docs/ROUTING.md", ["docs/ROUTING.md"]),
            ("echo x &> docs/ROUTING.md", ["docs/ROUTING.md"]),
            ("cat a | tee -a scripts/x.py", ["scripts/x.py"]),
            ("cat a | tee --append scripts/x.py", ["scripts/x.py"]),
            ("tee out.txt scripts/b.py < in", ["out.txt", "scripts/b.py"]),
            ("cp a scripts/y.py", ["scripts/y.py"]),
            ("cp -r a b scripts", ["scripts"]),
            ("cp -t scripts a b", ["scripts"]),
            ("cp --target-directory=scripts a", ["scripts"]),
            ("mv a docs/practices/p.md", ["docs/practices/p.md"]),
            ("mv -f -- a 'my dir/p.md'", ["my dir/p.md"]),
            ("sed -i '' -e s/a/b/ docs/CAPABILITIES.md", ["docs/CAPABILITIES.md"]),
            ("sed -i.bak s/a/b/ f.md", ["f.md"]),
            ("sed -i -e 's/a/b/' -e 's/c/d/' f.md", ["f.md"]),
            ("sed -ni 's/a/b/p' f.md g.md", ["f.md", "g.md"]),
            ("sed --in-place=.bak s/a/b/ f.md", ["f.md"]),
            ("sed -n 1p f.md", []),
            ("sed -e 's/in/out/' f.md", []),
            ("echo hi 2>&1", []),
            ("ls 2>/dev/null", ["/dev/null"]),
            ("echo a; cp x y.py && echo b > z.md", ["y.py", "z.md"]),
            ("cp a b\ncp c d", ["b", "d"]),
            ("cp a \\\n  b", ["b"]),
            ("echo 'unterminated > docs/ROUTING.md", ["docs/ROUTING.md"]),  # fallback split
            ("FOO=1 sudo cp a scripts/x.py", ["scripts/x.py"]),
            ("cat <<EOF > docs/ROUTING.md\nhello > not-a-target\nEOF", ["docs/ROUTING.md"]),
            ("cat > docs/n.md <<'EOF'\ncp a scripts/x.py\necho y > scripts/y.py\nEOF\ncp b docs/practices/p.md",
             ["docs/n.md", "docs/practices/p.md"]),  # here-document text is data, not commands
            ("cat <<-EOF > f.md\n\tbody > x\n\tEOF", ["f.md"]),
            ('grep x <<< "a > b" | tee out.log', ["out.log"]),  # a here-string opens no body
            ('echo "<<EOF"\ncp a scripts/x.py', ["scripts/x.py"]),  # no closing line, so nothing is hidden
            ("echo x > a.md > b.md", ["a.md", "b.md"]),
            ("echo x > a.md; echo y > a.md", ["a.md"]),
            ("ls -la", []),
            ("git status", []),
            ("_meta/brain lint", []),
            ("", []),
            ("cp a", []),
            ("tee", []),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(gate.bash_targets(command), expected)

    def test_targets_resolve_inside_the_brain(self):
        root = self.fake_brain()
        (root / "docs").mkdir()
        (root / "docs" / "ROUTING.md").write_text("map\n", encoding="utf-8")
        (root / "scripts").mkdir()

        def targets(**tool_input):
            return gate.targets({"cwd": str(root), "tool_input": tool_input}, root)

        self.assertEqual(targets(file_path="docs/ROUTING.md"), [("docs/ROUTING.md", True)])
        self.assertEqual(targets(file_path=str(root / "docs" / "new.md")), [("docs/new.md", False)])
        self.assertEqual(targets(notebook_path="docs/../docs/n.ipynb"), [("docs/n.ipynb", False)])
        self.assertEqual(targets(command="echo x > docs/ROUTING.md; cp a /etc/b; cp a ../out"),
                         [("docs/ROUTING.md", True)])
        self.assertEqual(targets(command="cp a scripts/"), [("scripts/", True)])  # an existing folder
        self.assertEqual(targets(file_path="/etc/hosts"), [])
        self.assertEqual(targets(file_path=str(root)), [])
        self.assertEqual(targets(), [])
        self.assertEqual(gate.targets({}, root), [])
        self.assertEqual(gate.targets({"tool_input": "x"}, root), [])
        self.assertEqual(gate.targets("not a dict", root), [])

    def test_load_rules(self):
        root = self.fake_brain(extra={
            "gates": [dict(DRAFT_RULE)],
            "gates_off": [{"path": "docs/CAPABILITIES.md", "why": "kept by hand"}],
            "gate_exempt": ["scripts/archive/**"]})
        rules, exempt = gate.load_rules(root, config.load(root))
        paths = [r.path for r in rules]
        self.assertIn(".claude/skills/lab-*/**", paths)  # {prefix} filled in
        self.assertNotIn(".claude/skills/brain-*/**", paths)  # only_in template
        self.assertNotIn("docs/CAPABILITIES.md", paths)  # gates_off
        self.assertIn("docs/ROUTING.md", paths)
        self.assertEqual(rules[0], gate.Rule(".claude/skills/lab-*/**", ["brain-write-skill"], False,
                                             "Skills are written through brain-write-skill, so they land in the "
                                             "routing map and pass lint.", True))
        self.assertEqual(rules[-1], gate.Rule("out/*.md", ["lab-draft"], True, DRAFT_RULE["why"], False))
        self.assertEqual([r.shipped for r in rules], [True] * (len(rules) - 1) + [False])
        self.assertEqual(exempt, ["scripts/archive/**"])

    def test_load_rules_in_the_template(self):
        root = self.fake_brain(prefix="template", role="template")
        rules, _exempt = gate.load_rules(root, config.load(root))
        paths = [r.path for r in rules]
        self.assertIn(".claude/skills/template-*/**", paths)
        self.assertIn(".claude/skills/brain-*/**", paths)

    def test_load_rules_skips_a_malformed_brain_rule_and_keeps_the_rest(self):
        root = self.fake_brain(extra={"gates": [{"skills": ["x"]}, {"path": "a/*", "skills": []},
                                                {"path": "b/*", "skills": [1]}, dict(DRAFT_RULE)]})
        rules, _exempt = gate.load_rules(root, config.load(root))
        self.assertEqual(rules[-1].path, "out/*.md")
        self.assertNotIn("a/*", [r.path for r in rules])

    def test_load_rules_with_no_shipped_file_has_only_the_brains_rules(self):
        root = self.draft_brain()
        (root / "_meta" / "gates.json").unlink()
        rules, exempt = gate.load_rules(root, config.load(root))
        self.assertEqual([r.path for r in rules], ["out/*.md"])
        self.assertEqual(exempt, [])

    def test_shipped_gates_file_is_pinned(self):
        shipped = json.loads((TEMPLATE_ROOT / "_meta" / "gates.json").read_text(encoding="utf-8"))
        self.assertEqual(shipped["exempt"], [])
        self.assertEqual(
            [(r["path"], r["skills"], r.get("only_in")) for r in shipped["rules"]],
            [(".claude/skills/{prefix}-*/**", ["brain-write-skill"], None),
             (".claude/skills/brain-*/**", ["brain-write-skill"], "template"),
             ("docs/ROUTING.md", ["brain-write-skill"], None),
             ("scripts/**", ["brain-write-script"], None),
             ("docs/CAPABILITIES.md", ["brain-write-script"], None),
             ("docs/practices/**", ["brain-write-practice"], None),
             ("docs/RETRO-LOG.md", ["brain-retro"], None),
             ("docs/UNCLASSIFIED-LOG.md", ["brain-retro"], None),
             ("docs/UPSTREAM.md", ["brain-upstream", "brain-sync"], None)])
        for rule in shipped["rules"]:
            self.assertTrue(rule["why"].endswith("."), rule)


class GateLintTest(GateCase):
    def lint_rules(self, root):
        return gate.lint_rules(root, config.load(root), list_skills(root))

    def test_lint_reports_rule_naming_missing_skill(self):
        root = self.draft_brain()
        self.assertEqual(self.lint_rules(root), [
            Finding(BROKEN, "gates", "rule for out/*.md names lab-draft, which does not exist")])
        self.make_skill(root, "lab-draft", "Does X. Does NOT do Y, which is lab-other.", "## Done when\n- ok")
        self.assertEqual(self.lint_rules(root), [])

    def test_lint_reports_every_missing_skill_of_every_rule(self):
        root = self.fake_brain(extra={"gates": [
            {"path": "a/*", "skills": ["lab-one", "lab-two"], "why": "x"},
            {"path": "b/*", "skills": ["lab-two"], "why": "y"}]})
        self.assertEqual([f.message for f in self.lint_rules(root)], [
            "rule for a/* names lab-one, which does not exist",
            "rule for a/* names lab-two, which does not exist",
            "rule for b/* names lab-two, which does not exist"])

    def test_lint_reports_a_gates_off_entry_without_why(self):
        root = self.fake_brain(extra={"gates_off": [
            {"path": "docs/ROUTING.md"}, {"path": "scripts/**", "why": "  "},
            {"path": "docs/CAPABILITIES.md", "why": "kept by hand"}, {"why": "no path"}]})
        self.assertEqual(self.lint_rules(root), [
            Finding(BROKEN, "gates_off", "entry for docs/ROUTING.md has no 'why'"),
            Finding(BROKEN, "gates_off", "entry for scripts/** has no 'why'"),
            Finding(BROKEN, "gates_off", "entry 4 has no 'path'")])

    def test_lint_reports_a_malformed_brain_rule(self):
        root = self.fake_brain(extra={"gates": [{"skills": ["lab-x"]}, {"path": "a/*"}, {"path": "b/*", "skills": "lab-x"}]})
        messages = [f.message for f in self.lint_rules(root)]
        self.assertEqual(len(messages), 3)
        self.assertTrue(all(m.startswith("entry ") for m in messages), messages)

    def test_lint_does_not_check_the_shipped_rules_skills(self):
        # The shipped rules name brain-* skills every brain holds; a later template-level test covers them.
        # fake_brain copies whichever brain-* skills the working tree has by now, so take them all out.
        root = self.fake_brain()
        shutil.rmtree(str(root / ".claude" / "skills"), ignore_errors=True)
        self.assertEqual(list_skills(root), [])
        self.assertEqual(self.lint_rules(root), [])

    def test_lint_reports_an_unreadable_shipped_file_but_not_a_missing_one(self):
        root = self.fake_brain()
        (root / "_meta" / "gates.json").write_text("{ broken", encoding="utf-8")
        found = self.lint_rules(root)
        self.assertEqual([(f.severity, f.subject) for f in found], [(BROKEN, "_meta/gates.json")])
        (root / "_meta" / "gates.json").unlink()
        self.assertEqual(self.lint_rules(root), [])

    def test_lint_rules_is_registered_with_lint(self):
        self.assertIn(gate.lint_rules, lint.EXTRA_CHECKS)
        root = self.draft_brain()
        self.assertIn(Finding(BROKEN, "gates", "rule for out/*.md names lab-draft, which does not exist"),
                      lint.all_findings(root, config.load(root)))
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 1)
        self.assertIn("BROKEN gates: rule for out/*.md names lab-draft, which does not exist", r.stdout)


if __name__ == "__main__":
    import unittest
    unittest.main()
