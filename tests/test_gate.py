from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
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
            f"Invoke the skill. {gate.SLASH_HINT} A one-time waiver needs the person's express say-so: "
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

    def state_base(self):
        """The shared folder the gate keeps session state in: under XDG_RUNTIME_DIR when that is a folder."""
        run = self.env.get("XDG_RUNTIME_DIR")
        return Path(run if run and Path(run).is_dir() else self.env["TMPDIR"]) / "brain-gate"

    def state_dir(self, root):
        digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
        return self.state_base() / digest

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
            ("ls /tmp; cp a b\ncp c scripts/z.py", "scripts/z.py"),
            ("cat > .claude/skills/lab-q/SKILL.md <<EOF\nhi\nEOF", ".claude/skills/lab-q/SKILL.md"),
            # A folder the command creates (or renames to) is a write into it, whether or not it exists yet.
            ("mkdir -p .claude/skills/lab-new && cp /tmp/SKILL.md .claude/skills/lab-new/", ".claude/skills/lab-new/"),
            ("cp -r /tmp/draft .claude/skills/lab-new", ".claude/skills/lab-new/"),
            ("mv .claude/skills/lab-old .claude/skills/lab-new", ".claude/skills/lab-new/"),
            ("cp -r /tmp/draft docs/practices", "docs/practices/"),
            # An apostrophe in a comment opens no quote: bash skips the comment and runs the write.
            ("# let's update the routing\necho x > docs/ROUTING.md", "docs/ROUTING.md"),
            ("# don't forget\ncp /tmp/a scripts/x.py", "scripts/x.py"),
            ("echo hi # it's done\necho x > docs/ROUTING.md", "docs/ROUTING.md"),
            ("# Write the new skill's file\ncat > .claude/skills/lab-new/SKILL.md <<'EOF'\nhello\nEOF",
             ".claude/skills/lab-new/SKILL.md"),
            ("echo a#b > docs/ROUTING.md", "docs/ROUTING.md"),  # a # inside a word is no comment
            ("x=abc; echo ${#x} > docs/ROUTING.md", "docs/ROUTING.md"),
            # Bash rewrites the word before it opens the file.
            ("echo x > $'docs/ROUTING.md'", "docs/ROUTING.md"),
            ('echo x > $"docs/ROUTING.md"', "docs/ROUTING.md"),
            ("echo x > $'docs\\x2fROUTING.md'", "docs/ROUTING.md"),
            ("echo x > $'docs\\057ROUTING.md'", "docs/ROUTING.md"),
            ("echo x > $'docs/ROUTING.md\\x00.bak'", "docs/ROUTING.md"),
            ("echo x > docs/{ROUTING,OTHER}.md", "docs/ROUTING.md"),
            ("echo x > docs/{OTHER,ROUTING}.md", "docs/ROUTING.md"),
            ("echo x > {docs,notes}/ROUTING.md", "docs/ROUTING.md"),
            ("echo x > docs/{OTHER,{ROUTING,X}}.md", "docs/ROUTING.md"),
            ("cp a scripts/{x,y}.py", "scripts/y.py"),  # cp a scripts/x.py scripts/y.py: the last word is written
            # A file-descriptor number is not an operand.
            ("cp a docs/ROUTING.md 2>&1", "docs/ROUTING.md"),
            ("mv a docs/ROUTING.md 2>&1 | head", "docs/ROUTING.md"),
            ("cp a scripts/x.py >/dev/null 2>&1", "scripts/x.py"),
            ("cp a scripts/x.py 2>/dev/null", "scripts/x.py"),
            # ln writes its last operand like cp and mv.
            ("ln -s /tmp/x scripts/y.py", "scripts/y.py"),
            ("ln -sf /tmp/x docs/ROUTING.md", "docs/ROUTING.md"),
            # Braces are expanded before cp, mv and ln pick their operands.
            ("cp docs/ROUTING.md{.bak,}", "docs/ROUTING.md"),
            ("mv docs/ROUTING.md{.new,}", "docs/ROUTING.md"),
            ("cp scripts/x.py{,.bak}", "scripts/x.py.bak"),
            # A # inside backticks, $(...) or ${...} is not a comment.
            ("echo `true #` > docs/ROUTING.md", "docs/ROUTING.md"),
            ("v=`git describe #tag`; echo $v > docs/ROUTING.md", "docs/ROUTING.md"),
            ("echo ${x:- #} > docs/ROUTING.md", "docs/ROUTING.md"),
            ("v=`git describe # don't fail`; echo $v > docs/ROUTING.md", "docs/ROUTING.md"),
            # Inside $(...) a # that starts a word IS a comment, as in bash: quotes and parentheses in it mean nothing.
            ("n=$(\n  grep -c x docs/a.md  # it's a count\n)\necho $n >> docs/RETRO-LOG.md", "docs/RETRO-LOG.md"),
            ("v=$(git describe --tags # don't fail on untagged\n)\necho \"$v\" > docs/ROUTING.md", "docs/ROUTING.md"),
            ("v=$(git log -1  # last commit (for the record\n)\n# don't touch it\necho \"$v\" > docs/ROUTING.md",
             "docs/ROUTING.md"),
            # A here-document inside "$(...)" is parsed as one, whatever quotes its body holds.
            ("git commit -m \"$(cat <<'EOF'\nFix the \"user's\" path\nEOF\n)\" && cp a scripts/x.py", "scripts/x.py"),
            ("git commit -m \"$(cat <<'EOF'\nline > one\n--> two\n# three (\nEOF\n)\"\ncp a scripts/x.py", "scripts/x.py"),
            ("git commit -m \"$(cat <<EOF\nit's\nEOF\n)\" ; echo x > docs/ROUTING.md", "docs/ROUTING.md"),
            ("echo \"a $(cat <<'E'\n\"\nE\n) b\" > docs/ROUTING.md", "docs/ROUTING.md"),
            # Commands inside a substitution run, quoted or not, and the word around it is still an operand.
            ('echo "$(cp a scripts/x.py)"', "scripts/x.py"),
            ("echo $(cp a scripts/x.py)", "scripts/x.py"),
            ('cp a "$(date)" docs/ROUTING.md', "docs/ROUTING.md"),
            ("cp $(echo a) docs/ROUTING.md", "docs/ROUTING.md"),
            ("tee >(cat) scripts/x.py", "scripts/x.py"),
            ("cat <(echo a) > docs/ROUTING.md", "docs/ROUTING.md"),
            # << inside arithmetic is a shift, not a here-document.
            ("x=$((1<<2))\ncp a scripts/x.py", "scripts/x.py"),
            ("(( y = 1 << 3 ))\necho x > docs/ROUTING.md", "docs/ROUTING.md"),
            ("for ((i=0; i<3; i++)); do echo x >> docs/RETRO-LOG.md; done", "docs/RETRO-LOG.md"),
            ("echo $[1<<2]\ncp a scripts/x.py", "scripts/x.py"),
            ("echo $(( 1 << 2 )) $((3 << 4)) > docs/ROUTING.md", "docs/ROUTING.md"),
            ("while (( n << 1 )); do cp a scripts/x.py; done", "scripts/x.py"),
            ("echo $((1 + 2)) # it's\ncp a scripts/x.py", "scripts/x.py"),  # balanced, so the comment is a comment
            # One target that cannot be resolved does not hide the others.
            ("echo x > $'\\uD800'; echo x > docs/ROUTING.md", "docs/ROUTING.md"),
            ("cp a $'\\ud800/x' scripts/y.py", "scripts/y.py"),
            # Reserved words before a command do not hide it.
            ("if true; then cp a scripts/x.py; fi", "scripts/x.py"),
            ("while x; do cp a docs/ROUTING.md; done", "docs/ROUTING.md"),
            ("{ cp a scripts/x.py; }", "scripts/x.py"),
            ("! cp a scripts/x.py", "scripts/x.py"),
            ("for f in a; do cp a docs/practices/; done", "docs/practices/"),
            ("if ! cp a scripts/x.py; then echo no; fi", "scripts/x.py"),
            ("until cp a scripts/x.py; do sleep 1; done", "scripts/x.py"),
            ("case x in a) cp a scripts/x.py ;; esac", "scripts/x.py"),
            ("if x\nthen\n  cp a scripts/x.py\nelse\n  true\nfi", "scripts/x.py"),
            # A here-document marker inside a comment opens no here-document.
            ("echo hi # <<EOF\ncp a scripts/x.py\nEOF", "scripts/x.py"),
            # (( and $(( are arithmetic only when they end in "))"; otherwise they open subshells, as in bash.
            ("((cp x scripts/y.py && cd a) && echo ok)", "scripts/y.py"),
            ("echo $((cp a scripts/x.py) )", "scripts/x.py"),
            ('echo "$((cp a scripts/x.py) )"', "scripts/x.py"),
            ("if (( 1 << 2 )); then cp a scripts/x.py; fi", "scripts/x.py"),
            ("a=1; (( a <<= 2 )) && cp a scripts/x.py", "scripts/x.py"),
            ("y=$[1<<2]\ncp a scripts/x.py", "scripts/x.py"),
            # A quote, group or substitution left open does not swallow what follows it.
            ("x=`cat <<EOF\nit's\nEOF`; cp a scripts/x.py", "scripts/x.py"),
            ("echo 'unterminated > docs/ROUTING.md", "docs/ROUTING.md"),
            ('echo "unterminated; cp a scripts/x.py', "scripts/x.py"),
            ("echo $((1 + 2; cp a scripts/x.py", "scripts/x.py"),
            ("(( 1 + 2; cp a scripts/x.py", "scripts/x.py"),
            ("echo $[1; cp a scripts/x.py", "scripts/x.py"),
            # A case pattern's ")" inside $(...) does not end the substitution.
            ('v="$(case $x in a) echo "it\'s" ;; esac)" && cp a scripts/x.py && echo \'done\'', "scripts/x.py"),
            ('v="$(case $x in (a) echo "it\'s" ;; b|c) echo b ;& *) echo z ;;& esac)" && cp a scripts/x.py && echo \'x\'',
             "scripts/x.py"),
            ('echo "$(echo "$(case a in a) echo "it\'s";; esac)")" && cp a scripts/x.py && echo \'x\'', "scripts/x.py"),
            ('v="$(case $x in a) echo "it\'s"\nesac)" && cp a scripts/x.py && echo \'done\'', "scripts/x.py"),
            # Inside $(...) a line that starts with the delimiter and goes on to a ")" ends the here-document (bash).
            ("git commit -m \"$(cat <<'EOF'\nFix the user's path\nEOF)\" && cp a scripts/x.py", "scripts/x.py"),
            ("git commit -m \"$(cat <<'EOF'\nFix the user's path\nEOF )\" && cp a scripts/x.py", "scripts/x.py"),
            ("git commit -m \"$(cat <<EOF\nit's\nEOF)\"; echo x > docs/ROUTING.md", "docs/ROUTING.md"),
            ("git commit -m \"$(cat <<-'EOF'\n\tit's\n\tEOF)\" && cp a scripts/x.py", "scripts/x.py"),
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

    def test_globs_in_a_target_are_expanded_as_bash_would(self):
        root = self.fake_brain()
        (root / "docs").mkdir()
        (root / "docs" / "ROUTING.md").write_text("map\n", encoding="utf-8")
        (root / "scripts").mkdir()
        (root / "scripts" / "a.py").write_text("x\n", encoding="utf-8")
        (root / ".brain").mkdir()
        (root / ".brain" / "gate-waiver.json").write_text("{}\n", encoding="utf-8")  # a glob needs something to match
        for command, rel in [("echo x > docs/ROUTIN?.md", "docs/ROUTING.md"),
                             ("echo x > docs/ROUTING.m*", "docs/ROUTING.md"),
                             ("echo x > docs/R[O]UTING.md", "docs/ROUTING.md"),
                             ("echo x > d*/ROUTING.md", "docs/ROUTING.md"),
                             ("echo x > ./docs/ROUT*", "docs/ROUTING.md"),
                             ("cat a | tee docs/ROUTING.m?", "docs/ROUTING.md"),
                             ("cp a docs/ROUTIN?.md", "docs/ROUTING.md"),
                             ("echo x > scripts/*.py", "scripts/a.py"),
                             ("echo x > scripts/*", "scripts/a.py"),
                             ("echo x > .br*/gate-waiver.json", ".brain/gate-waiver.json"),
                             ("echo x > \"docs\"/ROUTIN?.md", "docs/ROUTING.md")]:
            with self.subTest(command=command):
                self.assertIn(f"writing {rel}", self.denied(self.bash(root, command)))
        for command in ('echo x > "docs/ROUTIN?.md"', "echo x > docs/ROUTIN\\?.md", "echo x > docs/NOPE*.md",
                        "echo x > */ROUTING.md.bak"):
            with self.subTest(command=command):
                self.assert_silent(self.bash(root, command))  # quoted, or nothing to match: the literal name

    def test_bash_rewrites_are_followed_to_the_real_file(self):
        root = self.fake_brain()
        (root / "docs").mkdir()
        (root / "docs" / "ROUTING.md").write_text("map\n", encoding="utf-8")
        for command in ("echo x > $'docs/ROUTING.md'", 'echo x > $"docs/ROUTING.md"',
                        "echo x > docs/{ROUTING,OTHER}.md", "echo x > docs/{OTHER,ROUTING}.md",
                        "echo x > $'docs/ROUTIN\\x47.md'", "echo x > doc$'s'/ROUTING.md"):
            with self.subTest(command=command):
                self.assertIn("writing docs/ROUTING.md needs", self.denied(self.bash(root, command)))

    def test_cp_mv_and_ln_into_a_folder_that_exists_check_each_name_it_gets(self):
        root = self.fake_brain()
        for folder in (".claude/skills", "docs", ".brain", "scripts", "docs/practices"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        source = self.tmp.parent / "src"  # the folder with the space is a poor place for unquoted words
        source.mkdir()
        for name in ("ROUTING.md", "other.md"):
            (source / name).write_text("x\n", encoding="utf-8")
        (source / "lab-new").mkdir()
        src = str(source)
        cases = [
            (f"cp -r {src}/lab-new .claude/skills/", ".claude/skills/lab-new/"),
            (f"cp -r {src}/lab-new .claude/skills", ".claude/skills/lab-new/"),
            (f"cp -r {src}/lab-new/ .claude/skills", ".claude/skills/lab-new/"),
            (f"mv {src}/lab-new .claude/skills", ".claude/skills/lab-new/"),
            (f"cp {src}/ROUTING.md docs/", "docs/ROUTING.md"),
            (f"cp {src}/ROUTING.md docs", "docs/ROUTING.md"),
            (f"cp -t docs {src}/ROUTING.md", "docs/ROUTING.md"),
            (f"mv {src}/ROUTING.md docs", "docs/ROUTING.md"),
            (f"ln -s {src}/ROUTING.md docs/", "docs/ROUTING.md"),
            (f"cp {src}/*.md scripts/ && cp {src}/R*.md docs", "docs/ROUTING.md needs"),
            (f"cp {src}/{{ROUTING,other}}.md docs/", "docs/ROUTING.md"),
            (f"cp {src}/other.md docs/practices", "docs/practices/"),
            (f"cp {src}/other.md docs/practices/", "docs/practices/"),
        ]
        for command, rel in cases:
            with self.subTest(command=command):
                self.assertIn(rel, self.denied(self.bash(root, command)))
        gate_waiver = source / "gate-waiver.json"
        gate_waiver.write_text("{}\n", encoding="utf-8")
        for command in (f"cp {src}/gate-waiver.json .brain/", f"cp {src}/gate-waiver.json .brain", f"mv {src}/gate-waiver.json .brain",
                        f"ln -s {src}/gate-waiver.json .brain/", f"cp {src}/gate-waiver.* .brain/"):
            with self.subTest(command=command):
                self.assertIn("writing .brain/gate-waiver.json is refused", self.denied(self.bash(root, command)))
        for command in (f"cp {src}/other.md docs/", f"cp {src}/other.md .brain/", f"cp {src}/other.md /tmp/",
                        f"cp -r {src}/lab-new /tmp", f"mv {src}/other.md notes"):
            with self.subTest(command=command, passes=True):
                self.assert_silent(self.bash(root, command))

    def test_ln_is_a_write(self):
        root = self.fake_brain()
        for command, rel in [("ln -s /tmp/x .brain/gate-waiver.json", ".brain/gate-waiver.json"),
                             ("ln /tmp/x scripts/y.py", "scripts/y.py"), ("ln -sf /tmp/x docs/ROUTING.md", "docs/ROUTING.md")]:
            with self.subTest(command=command):
                self.assertIn(f"writing {rel}", self.denied(self.bash(root, command)))
        self.assert_silent(self.bash(root, "ln -s /tmp/x"))

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
                        "git commit -m 'update docs/ROUTING.md'",
                        "grep -n '>' docs/ROUTING.md", 'grep -- "-->" docs/ROUTING.md', "echo '>' docs/ROUTING.md",
                        'echo "a > b" docs/ROUTING.md', "echo \\> docs/ROUTING.md", "printf %s '>>' docs/RETRO-LOG.md",
                        "cp a notes/new", "cp a notes/new/",
                        "echo hi # > docs/ROUTING.md", "# let's not write to docs/ROUTING.md", "echo hi;# it's\nls",
                        'echo x > "docs/ROUTIN?.md"', "echo x > 'docs/{ROUTING,OTHER}.md'", "echo x > docs/ROUTIN?.md",
                        "ln -s /tmp/x", "ln -s /tmp/x /tmp/y", "cp a /tmp/docs/ROUTING.md 2>&1",
                        "cat docs/ROUTING.md 2>&1", "cp docs/ROUTING.md /tmp/out 2>&1",
                        "if true; then echo hi; fi", "for f in a; do echo $f; done", "{ echo hi; }", "echo done fi then",
                        "while read x; do echo $x; done < docs/ROUTING.md", "cp docs/ROUTING.md{.bak,} /tmp/",
                        "echo `true #` | cat", "cat <<EOF\ncp a scripts/x.py\nEOF",
                        # the commit idiom, with a body of every awkward kind, writes no ruled file
                        "git commit -m \"$(cat <<'EOF'\nFix the \"user's\" path\nEOF\n)\"",
                        "git commit -m \"$(cat <<'EOF'\nUpdate docs/ROUTING.md > scripts/x.py\n--> arrows # and (\nEOF\n)\"",
                        "git commit -m \"$(cat <<'EOF'\ncp a scripts/x.py\necho x > docs/ROUTING.md\nEOF\n)\" && git status",
                        "v=$(cat <<EOF\nit's\nEOF\n)\necho \"$v\"", "x=$((1<<2))", "(( y = 1 << 3 ))\necho $y",
                        "echo $[1<<2]", "n=$(grep -c x docs/a.md  # it's a count\n)\necho $n", "cat <(echo a)",
                        "echo \"$(date)\" docs/ROUTING.md",
                        # arithmetic, and a (( that is a subshell
                        "x=$((1<<2)); echo $x", "if (( 1 << 2 )); then echo yes; fi", "a=1; (( a <<= 2 )); echo $a",
                        "for ((i=0; i<3; i++)); do echo $i; done", "echo $(( (1 + 2) * 3 ))",
                        "x=$(( $(wc -l < docs/ROUTING.md) + 1 ))", "((cd docs && cat ROUTING.md) && echo ok)",
                        # a case inside a substitution
                        'v="$(case $x in a) echo "it\'s" ;; esac)" && echo "$v" && echo \'done\'',
                        'v="$(case $x in a) echo "> docs/ROUTING.md " ;; esac)"',
                        "kind=$(case docs/ROUTING.md in *.md) echo doc;; *) echo other;; esac); echo \"$kind\"",
                        # a here-document that "EOF)" closes inside $(...) hides its body; at the top level it is body text
                        "git commit -m \"$(cat <<'EOF'\nFix the user's path > scripts/x.py\ncp a docs/ROUTING.md\nEOF)\"",
                        "git commit -m \"$(cat <<'EOF'\nFix the user's path\nEOF)\" && git log -1",
                        "cat <<EOF\nEOF) > docs/ROUTING.md\nEOF"):
            with self.subTest(command=command):
                self.assert_silent(self.bash(root, command))

    def test_a_double_parenthesis_that_is_not_arithmetic_runs_its_commands(self):
        root = self.fake_brain()
        (root / "a").mkdir()
        # The `cd` is not followed: a relative target after it is not read, an absolute one still is.
        r = self.hook(root, "check", "Bash", cwd=root / "a", command="((cd a && cp x ../scripts/y.py) && echo ok)")
        self.assert_silent(r)
        r = self.hook(root, "check", "Bash", cwd=root / "a", command=f"((cd a && cp x '{root}/scripts/y.py') && echo ok)")
        self.assertIn("writing scripts/y.py needs brain-write-script", self.denied(r))

    def test_a_command_nested_too_deep_to_check_is_refused(self):
        root = self.fake_brain()
        over, limit = gate.MAX_NESTING + 1, gate.MAX_NESTING
        for command in ("echo " + "$(" * over + "true" + ")" * over,
                        "ls; echo " + "$(" * over + ")" * over,
                        "cat " + "<(" * over + "x" + ")" * over,
                        'echo "' + '$(echo "' * over + "x" + '")' * over + '"',
                        "echo " + "$((" * over + "true" + ") ) " * over):  # no "))", so none is arithmetic
            with self.subTest(command=command[:40]):
                reason = self.denied(self.bash(root, command))
                self.assertIn(f"more than {limit} levels deep", reason)
                self.assertIn("Split it into smaller commands", reason)
        self.assertTrue(self.status(root, "--session", "s1")[3].startswith(
            f"last refusal: a command nested more than {limit} levels deep ("))
        # At the limit the command is read as usual.
        self.assert_silent(self.bash(root, "echo " + "$(" * limit + "true" + ")" * limit))
        self.assertIn("writing scripts/x.py needs",
                      self.denied(self.bash(root, "echo " + "$(" * limit + "cp a scripts/x.py" + ")" * limit)))

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

    def test_one_unresolvable_target_does_not_fail_the_whole_call_open(self):
        root = self.fake_brain()
        # A lone surrogate (here also straight in the payload's text) cannot name a file; the write beside it is still judged.
        for command in ("echo x > $'\\uD800'; echo x > docs/ROUTING.md", "echo x > \ud800; echo x > docs/ROUTING.md"):
            with self.subTest(command=command):
                self.assertIn("writing docs/ROUTING.md needs", self.denied(self.bash(root, command)))
        self.assert_silent(self.hook(root, "check", "Write", file_path="\ud800"))
        self.assert_silent(self.bash(root, "echo x > $'\\uD800'"))

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
        self.assertEqual(list(Path(self.env["XDG_RUNTIME_DIR"]).glob("*")), [self.state_dir(root).parent])
        self.assertEqual(list(Path(self.env["TMPDIR"]).glob("*")), [])  # the runtime folder is preferred
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


SCRIPT_WHY = "Scripts follow brain-write-script: placement, read-only by default, tests."
PRACTICE_WHY = "Practices need evidence, a duplicate check and the index, through brain-write-practice."
DEPLOY_RULE = {"path": "scripts/deploy/**", "skills": ["lab-deploy"], "why": "Deploys go through lab-deploy."}
WAIVE_HINT = "Invoke the skill{s}. " + gate.SLASH_HINT + " A one-time waiver needs the person's express say-so: " \
             "_meta/brain gate waive {skill} \"<reason, and who said so>\""


class GateObligationsTest(GateCase):
    """Every ruled target of a call, and every rule that matches it, must be satisfied (ruling R18)."""

    def test_every_ruled_target_of_a_command_must_be_satisfied(self):
        root = self.fake_brain()
        self.ran(root, "brain-write-script")
        commands = ("cp a scripts/x.py && echo y > docs/ROUTING.md", "echo y > docs/ROUTING.md && cp a scripts/x.py",
                    "tee scripts/x.py docs/ROUTING.md", "echo y > docs/ROUTING.md > scripts/x.py")
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.denied(self.bash(root, command)),
                                 refusal("docs/ROUTING.md", ["brain-write-skill"], ROUTING_WHY))
        self.ran(root, "brain-write-skill")
        for command in commands:
            with self.subTest(command=command, ran="both"):
                self.assert_silent(self.bash(root, command))

    def test_the_denial_names_every_unsatisfied_target_and_owner_set(self):
        root = self.fake_brain()
        reason = self.denied(self.bash(root, "cp a scripts/x.py && echo y > docs/ROUTING.md"))
        self.assertEqual(reason, (
            f"skill gate: writing scripts/x.py needs brain-write-script to run first in this session. {SCRIPT_WHY} "
            f"Writing docs/ROUTING.md needs brain-write-skill to run first. {ROUTING_WHY} "
            + WAIVE_HINT.format(s="s", skill="brain-write-script")))
        # The first unsatisfied target is the one remembered.
        self.assertTrue(self.status(root, "--session", "s1")[3].startswith(
            "last refusal: scripts/x.py needs brain-write-script"))

    def test_a_denial_spends_and_consumes_nothing(self):
        root = self.draft_brain()
        (root / "out").mkdir()
        for name in ("a.md", "b.md"):
            (root / "out" / name).write_text("draft\n", encoding="utf-8")
        self.ran(root, "lab-draft")
        # One run cannot cover two revisions: the second file is refused and the run is still there.
        reason = self.denied(self.bash(root, "sed -i s/a/b/ out/a.md out/b.md"))
        self.assertEqual(reason, refusal("out/b.md", ["lab-draft"], DRAFT_RULE["why"]))
        lines = self.status(root, "--session", "s1")
        self.assertEqual(lines[1], "ran: lab-draft x1")
        self.assertTrue(lines[3].startswith("last refusal: out/b.md needs lab-draft"), lines[3])
        # A second run covers both, and each revision spends one.
        self.ran(root, "lab-draft")
        message = self.notice(self.bash(root, "sed -i s/a/b/ out/a.md out/b.md"))
        self.assertIn("out/a.md", message)
        self.assertIn("out/b.md", message)
        self.assertEqual(self.status(root, "--session", "s1")[1], "ran: lab-draft x0")
        self.denied(self.bash(root, "sed -i s/a/b/ out/a.md"))

    def test_creating_files_spends_nothing_even_next_to_a_revision(self):
        root = self.draft_brain()
        (root / "out").mkdir()
        (root / "out" / "a.md").write_text("draft\n", encoding="utf-8")
        self.ran(root, "lab-draft")
        message = self.notice(self.bash(root, "echo new > out/new.md && sed -i s/a/b/ out/a.md"))
        self.assertIn("out/a.md", message)
        self.assertNotIn("out/new.md", message)
        self.assertEqual(self.status(root, "--session", "s1")[1], "ran: lab-draft x0")

    def test_a_denial_leaves_an_armed_waiver_alone(self):
        root = self.fake_brain()
        self.waive(root, "brain-write-skill", "Dana said so")
        # The waiver covers the ROUTING.md write only; the script write still needs its skill.
        reason = self.denied(self.bash(root, "cp a scripts/x.py && echo y > docs/ROUTING.md"))
        self.assertEqual(reason, refusal("scripts/x.py", ["brain-write-script"], SCRIPT_WHY))
        self.assertTrue(self.waiver_path(root).exists())
        self.assertEqual(len(self.waiver_log(root)), 1)  # armed, never used
        self.ran(root, "brain-write-script")
        message = self.notice(self.bash(root, "cp a scripts/x.py && echo y > docs/ROUTING.md"))
        self.assertIn("waiver", message)
        self.assertIn("docs/ROUTING.md", message)
        self.assertFalse(self.waiver_path(root).exists())
        armed, used = self.waiver_log(root)
        self.assertEqual(used[1:], ["used", "brain-write-skill", "Dana said so", "docs/ROUTING.md"])

    def test_one_waiver_covers_every_target_of_the_call_that_names_its_skill(self):
        root = self.fake_brain()
        self.waive(root, "brain-write-skill", "Dana said so")
        message = self.notice(self.bash(root, "cp a docs/ROUTING.md && cp b .claude/skills/lab-q/SKILL.md"))
        self.assertIn("waiver", message)
        self.assertFalse(self.waiver_path(root).exists())
        rows = self.waiver_log(root)
        self.assertEqual([row[1] for row in rows], ["armed", "used", "used"])
        self.assertEqual([row[4] for row in rows[1:]], ["docs/ROUTING.md", ".claude/skills/lab-q/SKILL.md"])

    def test_a_symlink_ruled_under_two_owners_needs_both(self):
        root = self.fake_brain()
        (root / "scripts").mkdir()
        (root / "docs").mkdir()
        (root / "docs" / "practices").symlink_to(root / "scripts")  # docs/practices/x.py is scripts/x.py
        self.ran(root, "brain-write-practice")
        self.assertEqual(self.denied(self.write(root, "docs/practices/x.py")),
                         refusal("scripts/x.py", ["brain-write-script"], SCRIPT_WHY))
        self.ran(root, "brain-write-script", session="s2")
        self.assertEqual(self.denied(self.write(root, "docs/practices/x.py", session="s2")),
                         refusal("docs/practices/x.py", ["brain-write-practice"], PRACTICE_WHY))
        self.ran(root, "brain-write-script")
        self.assert_silent(self.write(root, "docs/practices/x.py"))

    def test_every_rule_that_matches_a_path_must_be_satisfied(self):
        root = self.fake_brain(extra={"gates": [dict(DEPLOY_RULE)]})
        both = (f"skill gate: writing scripts/deploy/x.sh needs brain-write-script to run first in this session. "
                f"{SCRIPT_WHY} It also needs lab-deploy to run first. {DEPLOY_RULE['why']} "
                + WAIVE_HINT.format(s="s", skill="brain-write-script"))
        self.assertEqual(self.denied(self.write(root, "scripts/deploy/x.sh")), both)
        self.ran(root, "brain-write-script")  # the shipped rule alone is no longer enough
        self.assertEqual(self.denied(self.write(root, "scripts/deploy/x.sh")),
                         refusal("scripts/deploy/x.sh", ["lab-deploy"], DEPLOY_RULE["why"]))
        self.ran(root, "lab-deploy", session="s2")  # nor is the brain's rule alone
        self.assertEqual(self.denied(self.write(root, "scripts/deploy/x.sh", session="s2")),
                         refusal("scripts/deploy/x.sh", ["brain-write-script"], SCRIPT_WHY))
        self.ran(root, "lab-deploy")
        self.assert_silent(self.write(root, "scripts/deploy/x.sh"))
        self.assert_silent(self.bash(root, "cp a scripts/deploy/y.sh"))
        # A path under the shipped rule only still needs only that rule's skill.
        self.assert_silent(self.write(root, "scripts/other.py"))

    def test_a_waiver_covers_only_the_rules_naming_its_skill(self):
        root = self.fake_brain(extra={"gates": [dict(DEPLOY_RULE)]})
        self.waive(root, "brain-write-script", "Dana said so")
        self.assertEqual(self.denied(self.write(root, "scripts/deploy/x.sh")),
                         refusal("scripts/deploy/x.sh", ["lab-deploy"], DEPLOY_RULE["why"]))
        self.assertTrue(self.waiver_path(root).exists())
        self.ran(root, "lab-deploy")
        self.assertIn("waiver", self.notice(self.write(root, "scripts/deploy/x.sh")))
        self.assertFalse(self.waiver_path(root).exists())

    def test_a_brain_rule_inside_a_shipped_glob_is_not_shadowed(self):
        root = self.fake_brain(extra={"gates": [dict(DEPLOY_RULE)]})
        self.ran(root, "brain-write-script")
        self.assertIn("needs lab-deploy", self.denied(self.bash(root, "echo x > scripts/deploy/a.sh")))
        self.assert_silent(self.bash(root, "echo x > scripts/build/a.sh"))


class GateReservedPathsTest(GateCase):
    """The waiver and its log are written by `gate waive` only; no skill run or waiver opens them."""

    RESERVED = (".brain/gate-waiver.json", ".brain/gate-waivers.log")

    def assert_reserved(self, r, rel):
        reason = self.denied(r)
        self.assertIn(f"writing {rel} is refused", reason)
        self.assertIn("_meta/brain gate waive", reason)
        self.assertIn("No skill run opens", reason)

    def test_the_waiver_files_cannot_be_written_by_the_tools(self):
        root = self.fake_brain()
        for rel in self.RESERVED:
            for tool in ("Write", "Edit"):
                with self.subTest(rel=rel, tool=tool):
                    self.assert_reserved(self.write(root, rel, tool=tool), rel)
            for command in (f"echo x > {rel}", f"echo x >> {rel}", f"cat a | tee -a {rel}", f"cp /tmp/forged {rel}",
                            f"mv /tmp/forged {rel}", f"sed -i s/a/b/ {rel}", f"echo x > ./.brain/../{rel}",
                            f"cp /tmp/forged {rel}{{.bak,}}", f"ln -s /tmp/x {rel}{{,}}"):
                with self.subTest(rel=rel, command=command):
                    self.assert_reserved(self.bash(root, command), rel)
        self.assertFalse((root / ".brain").exists())

    def test_nothing_opens_the_waiver_files(self):
        root = self.fake_brain(extra={"gate_exempt": [".brain/**"]})
        for skill in ("brain-write-skill", "brain-write-script", "brain-write-practice", "brain-retro",
                      "brain-upstream", "brain-sync", "lab-anything"):
            self.ran(root, skill)
        self.waive(root, "brain-write-skill", "Dana said so")
        for rel in self.RESERVED:
            with self.subTest(rel=rel):
                self.assert_reserved(self.write(root, rel), rel)
                self.assert_reserved(self.bash(root, f"echo x > {rel}"), rel)
        self.assertTrue(self.waiver_path(root).exists())  # still armed, and not rewritten
        self.assertEqual(len(self.waiver_log(root)), 1)

    def test_a_forged_waiver_never_gets_in(self):
        root = self.fake_brain()
        forged = '{"skill": "brain-write-skill", "reason": "forged"}'
        self.assert_reserved(self.bash(root, f"mkdir -p .brain && echo '{forged}' > .brain/gate-waiver.json"),
                             ".brain/gate-waiver.json")
        self.assertFalse(self.waiver_path(root).exists())
        self.denied(self.write(root, "docs/ROUTING.md"))

    def test_the_protection_does_not_need_the_config(self):
        root = self.fake_brain()
        (root / "brain.json").write_text("{ not json", encoding="utf-8")
        self.assert_reserved(self.write(root, ".brain/gate-waiver.json"), ".brain/gate-waiver.json")

    def test_reading_the_waiver_files_and_writing_beside_them_is_fine(self):
        root = self.fake_brain()
        self.waive(root, "brain-retro", "Dana said so")
        for command in ("cat .brain/gate-waiver.json", "grep armed .brain/gate-waivers.log", "ls .brain",
                        "cp .brain/gate-waivers.log /tmp/copy.log", "echo x > .brain/other.json"):
            with self.subTest(command=command):
                self.assert_silent(self.bash(root, command))
        self.assert_silent(self.write(root, ".brain/other.json"))

    def test_waive_still_arms_and_a_ruled_write_still_uses_it(self):
        root = self.fake_brain()
        self.waive(root, "brain-write-skill", "Dana said so")
        self.assertIn("waiver", self.notice(self.write(root, "docs/ROUTING.md")))


class GateStateDirTest(GateCase):
    def mode(self, path):
        return stat.S_IMODE(path.stat().st_mode)

    def test_state_lives_under_the_runtime_folder_when_there_is_one(self):
        root = self.fake_brain()
        self.ran(root, "brain-write-skill")
        run = Path(self.env["XDG_RUNTIME_DIR"])
        self.assertEqual(self.state_dir(root).parent, run / "brain-gate")
        self.assertTrue((run / "brain-gate").is_dir())
        self.assertEqual(oct(self.mode(run / "brain-gate")), oct(0o700))  # private to the user, like its parent
        self.assertEqual(oct(self.mode(self.state_dir(root))), oct(0o700))
        self.assertEqual(list(Path(self.env["TMPDIR"]).iterdir()), [])  # nothing in the shared temp folder

    def without_runtime_dir(self, value=None):
        if value is None:
            del self.env["XDG_RUNTIME_DIR"]
        else:
            self.env["XDG_RUNTIME_DIR"] = value

    def test_without_a_runtime_folder_the_temp_folder_is_sticky_and_world_writable(self):
        for value in (None, "", str(self.tmp / "no-such-folder")):
            with self.subTest(runtime=value):
                self.without_runtime_dir() if value is None else self.without_runtime_dir(value)
                root = self.fake_brain()
                self.ran(root, "brain-write-skill")
                shared = Path(self.env["TMPDIR"]) / "brain-gate"
                self.assertEqual(self.state_dir(root).parent, shared)
                self.assertEqual(oct(self.mode(shared)), oct(0o1777))
                self.assertEqual(oct(self.mode(self.state_dir(root))), oct(0o700))
                # The same when the first thing to touch the state is a refusal in another brain.
                other = self.fake_brain()
                self.denied(self.write(other, "docs/ROUTING.md"))
                self.assertEqual(oct(self.mode(self.state_dir(other))), oct(0o700))
                shutil.rmtree(str(shared))

    def test_a_umask_does_not_narrow_the_shared_directory(self):
        self.without_runtime_dir()
        root = self.fake_brain()
        old = os.umask(0o077)
        try:
            self.ran(root, "brain-write-skill")
        finally:
            os.umask(old)
        self.assertEqual(oct(self.mode(self.state_dir(root).parent)), oct(0o1777))

    def test_a_symlinked_session_folder_is_not_trusted_or_written_through(self):
        root = self.fake_brain()
        self.ran(root, "brain-retro")
        folder = self.state_dir(root)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        forged = elsewhere / "s1.json"
        forged.write_text(json.dumps({"ran": {"brain-write-skill": 9}, "last_refusal": None}), encoding="utf-8")
        shutil.rmtree(str(folder))
        folder.symlink_to(elsewhere)
        before = forged.read_text(encoding="utf-8")
        # The forged runs do not count, and since nothing can be kept there the write is let through with a warning.
        message = self.notice(self.write(root, "docs/ROUTING.md"))
        self.assertTrue(message.startswith("skill gate: cannot keep session state"), message)
        self.assertIn("docs/ROUTING.md", message)
        self.assertIn("error", self.notice(self.hook(root, "record", "Skill", skill="brain-write-skill")).lower())
        self.assertEqual(sorted(p.name for p in elsewhere.iterdir()), ["s1.json"])  # nothing written through
        self.assertEqual(forged.read_text(encoding="utf-8"), before)
        self.assertEqual(self.status(root, "--session", "s1")[1], "ran: nothing")

    def test_a_session_folder_with_the_wrong_mode_is_not_trusted_or_written_through(self):
        root = self.fake_brain()
        self.ran(root, "brain-write-skill")
        folder = self.state_dir(root)
        state = folder / "s1.json"
        before = state.read_text(encoding="utf-8")
        for mode in (0o755, 0o770, 0o500):
            with self.subTest(mode=oct(mode)):
                os.chmod(str(folder), mode)
                try:
                    message = self.notice(self.write(root, "docs/ROUTING.md"))  # the recorded run is not believed
                    self.assertTrue(message.startswith("skill gate: cannot keep session state"), message)
                    self.assertIn("error", self.notice(
                        self.hook(root, "record", "Skill", skill="brain-retro")).lower())
                    self.assertEqual(state.read_text(encoding="utf-8"), before)
                    self.assertEqual(sorted(p.name for p in folder.iterdir()), ["s1.json"])
                finally:
                    os.chmod(str(folder), 0o700)
        self.assert_silent(self.write(root, "docs/ROUTING.md"))  # and right again once it is private

    def test_state_that_cannot_be_kept_fails_open(self):
        root = self.fake_brain()
        self.state_base().write_text("in the way", encoding="utf-8")  # no state can be kept
        r = self.hook(root, "record", "Skill", skill="brain-write-skill")
        self.assertIn("skill gate error", self.notice(r))
        # A refusal nobody could ever satisfy is not a refusal: the write goes through, with a warning.
        message = self.notice(self.write(root, "docs/ROUTING.md"))
        self.assertTrue(message.startswith("skill gate: cannot keep session state"), message)
        self.assertIn("docs/ROUTING.md", message)
        self.assertIn("write allowed", message)
        self.assert_silent(self.write(root, "notes/a.md"))
        self.assert_silent(self.bash(root, "ls"))


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
            # An open quote does not swallow the rest (bash would not run it either way).
            ("echo 'unterminated > docs/ROUTING.md", ["docs/ROUTING.md"]),
            ("echo hi > docs/ROUTING.md\necho 'unterminated", ["docs/ROUTING.md"]),
            ("grep -n '>' docs/ROUTING.md", []),
            ('grep -- "-->" docs/ROUTING.md', []),
            ("echo '>' docs/ROUTING.md", []),
            ("echo \\> docs/ROUTING.md", []),
            ("echo '>' > docs/ROUTING.md", ["docs/ROUTING.md"]),
            ("grep '>' a.md > out.md", ["out.md"]),
            ('echo "a>b" > c.md', ["c.md"]),
            ("echo x >'my file.md'", ["my file.md"]),
            ("echo x > my\\ file.md", ["my file.md"]),
            ("echo `date > a.md`", ["a.md"]),
            ("cp /tmp/SKILL.md .claude/skills/lab-new/", [".claude/skills/lab-new/"]),
            # comments
            ("# only a comment", []),
            ("# it's a comment\necho x > a.md", ["a.md"]),
            ("echo hi # > a.md", []),
            ("echo hi; # it's a comment\ncp a b.md", ["b.md"]),
            ("echo a#b > c.md", ["c.md"]),
            ("echo ${#x} > c.md", ["c.md"]),
            ("echo '#' > c.md", ["c.md"]),
            ("echo x\\# > c.md", ["c.md"]),
            # quoting and brace expansion
            ("echo x > $'a\\tb'", ["a\tb"]),
            ("echo x > $'it\\'s'", ["it's"]),
            ("echo x > $'a\\\\b\\x41\\101'", ["a\\bAA"]),
            ("echo x > $'a\\x00b'", ["a"]),
            ("echo x > $'unterminated", ["$'unterminated"]),  # left open: plain characters
            ('echo x > $"a b"', ["a b"]),
            ("echo x > a$'b'c", ["abc"]),
            ("echo x > docs/{a,b}.md", ["docs/a.md", "docs/b.md"]),
            ("echo x > {a,b}/{c,d}", ["a/c", "a/d", "b/c", "b/d"]),
            ("echo x > a{b,c{d,e}}", ["ab", "acd", "ace"]),
            ("echo x > a{b}c", ["a{b}c"]),
            ("echo x > a{,b}", ["a", "ab"]),
            ("echo x > 'a{b,c}'", ["a{b,c}"]),
            ('echo x > a\\{b,c}', ["a{b,c}"]),
            ("echo x > ${HOME}/{a,b}", ["${HOME}/a", "${HOME}/b"]),
            ("cp a {b,c}.md", ["c.md"]),  # bash copies a and b.md into c.md: the last word is what is written
            ("cp docs/ROUTING.md{.bak,}", ["docs/ROUTING.md"]),
            ("mv docs/ROUTING.md{.new,}", ["docs/ROUTING.md"]),
            ("cp x{,.bak}", ["x.bak"]),
            ("tee {a,b}.md", ["a.md", "b.md"]),
            ("sed -i s/a/b/ {a,b}.md", ["a.md", "b.md"]),
            ("echo x > {a,b}.md", ["a.md", "b.md"]),
            # file-descriptor numbers
            ("cp a b 2>&1", ["b"]),
            ("cp a b 1>&2", ["b"]),
            ("cp a b >/dev/null 2>&1", ["/dev/null", "b"]),
            ("cp a b 2>/dev/null", ["/dev/null", "b"]),
            ("cp a 2 > c.md", ["c.md", "2"]),  # separated by a space, 2 is an operand
            ("echo 2> c.md", ["c.md"]),
            # ln
            ("ln -s /tmp/x .brain/gate-waiver.json", [".brain/gate-waiver.json"]),
            ("ln -sf -- /tmp/x y", ["y"]),
            ("ln -s /tmp/x", []),
            ("ln -t docs /tmp/x", ["docs"]),
            ("FOO=1 sudo cp a scripts/x.py", ["scripts/x.py"]),
            ("cat <<EOF > docs/ROUTING.md\nhello > not-a-target\nEOF", ["docs/ROUTING.md"]),
            ("cat > docs/n.md <<'EOF'\ncp a scripts/x.py\necho y > scripts/y.py\nEOF\ncp b docs/practices/p.md",
             ["docs/n.md", "docs/practices/p.md"]),  # here-document text is data, not commands
            ("cat <<-EOF > f.md\n\tbody > x\n\tEOF", ["f.md"]),
            ('grep x <<< "a > b" | tee out.log', ["out.log"]),  # a here-string opens no body
            ('echo "<<EOF"\ncp a scripts/x.py', ["scripts/x.py"]),  # quoted: no here-document
            ("cat <<EOF\ncp a scripts/x.py", ["scripts/x.py"]),  # no closing line, so nothing is hidden
            ("echo hi # <<EOF\ncp a scripts/x.py\nEOF", ["scripts/x.py"]),
            ("cat <<EOF >a.md <<'END' >b.md\nx > no\nEOF\ny > no\nEND\ncp c d.md", ["a.md", "b.md", "d.md"]),
            ("cat <<-\"EOF\" > f.md\n\t\tbody\n\tEOF\ncp a g.md", ["f.md", "g.md"]),
            ("echo `true #` > a.md", ["a.md"]),
            ("v=`git describe #tag`; echo $v > a.md", ["a.md"]),
            ("echo ${x:- #} > a.md", ["a.md"]),
            ("v=`git describe # don't fail`; echo $v > a.md", ["a.md"]),
            ("n=$(\n  grep -c x docs/a.md  # it's a count\n)\necho $n >> b.md", ["b.md"]),
            ("v=$(git log -1  # last commit (for the record\n)\n# don't touch it\necho $v > c.md", ["c.md"]),
            ("echo $(true #) > a.md", []),  # the comment swallows the ")": bash cannot parse this either
            ("git commit -m \"$(cat <<'EOF'\nFix the \"user's\" path\nEOF\n)\" && cp a b.md", ["b.md"]),
            ("git commit -m \"$(cat <<'EOF'\nFix the \"user's\" path > x\nEOF\n)\"", []),
            ("echo \"$(cp a b.md; echo hi > c.md)\" > d.md", ["b.md", "c.md", "d.md"]),
            ("echo $(echo $(cp a b.md))", ["b.md"]),
            ("cp a \"$(date)\" docs/b.md", ["docs/b.md"]),
            ("cp $(echo a) docs/b.md", ["docs/b.md"]),
            ("x=$(cp a b.md) && cp c d.md", ["b.md", "d.md"]),
            ("tee >(cat > a.md) b.md", ["a.md", "b.md"]),  # >(..) is an argument, not a file
            ("cat <(echo a) <(echo b) > c.md", ["c.md"]),
            ("x=$((1<<2))\ncp a b.md", ["b.md"]),
            ("(( y = 1 << 3 ))\necho x > a.md", ["a.md"]),
            ("echo $((1 + (2 * 3))) > a.md", ["a.md"]),
            ("echo $[1<<2] > a.md", ["a.md"]),
            ("for ((i=0; i<3; i++)); do cp a b.md; done", ["b.md"]),
            ("cat << > a.md", ["a.md"]),  # no delimiter word: no here-document
            ("cat <<EOF > a.md\nx\nEOF", ["a.md"]),
            ("echo $((1 + 2)) # it's\ncp a b.md", ["b.md"]),
            ("(true # it's\n) > a.md", ["a.md"]),  # in a plain subshell it is a comment
            # (( and $(( are arithmetic only when they close with "))"
            ("((cd a && cp x ../scripts/y.py) && echo ok)", ["../scripts/y.py"]),
            ("echo $((cp a b.md) )", ["b.md"]),
            ('echo "$((cp a b.md) )"', ["b.md"]),
            ("(( (1 + 2) * 3 )) && cp a b.md", ["b.md"]),
            ("echo $(( (1 + 2) * 3 )) > a.md", ["a.md"]),
            ("if (( 1 << 2 )); then cp a b.md; fi", ["b.md"]),
            ("a=1; (( a <<= 2 )) && cp a b.md", ["b.md"]),
            # nothing left open swallows the rest
            ('echo "unterminated; cp a b.md', ["b.md"]),
            ('echo "$(date)" "open; cp a b.md', ["b.md"]),
            ("echo $((1 + 2; cp a b.md", ["b.md"]),
            ("(( 1 + 2; cp a b.md", ["b.md"]),
            ("echo $[1; cp a b.md", ["b.md"]),
            ("echo ${x\n# it's\ncp a b.md", ["b.md"]),
            ("x=`cat <<EOF\nit's\nEOF`; cp a b.md", ["b.md"]),
            ("echo $(cp a b.md", ["b.md"]),
            # case patterns inside $(...)
            ('v="$(case $x in a) echo "it\'s" ;; esac)" && cp a b.md && echo \'done\'', ["b.md"]),
            ('v="$(case $x in a) echo "> b.md" ;; esac)"', []),
            ("x=$(case $1 in (a) cp a b.md;; esac)", ["b.md"]),
            ("x=$(case a in a) cp a b.md;; esac; cp c d.md)", ["b.md", "d.md"]),
            ("x=$(case a in a) echo x ;; esac) > e.md", ["e.md"]),
            ("x=$(echo case a in b) > e.md", ["e.md"]),  # not a case: the ")" ends the substitution
            ('x="$(echo > case; for f in a; do :; done)" && cp a b.md && echo "x"', ["case", "b.md"]),  # a file name
            # "EOF)" ends a here-document inside $(...), not at the top level
            ("echo \"$(cat <<'EOF'\nit's > a.md\nEOF)\" && cp a b.md", ["b.md"]),
            ("echo \"$(cat <<'EOF'\nit's > a.md\nEOF )\" > c.md", ["c.md"]),
            ("cat <<EOF\nEOF) > a.md\nEOF\ncp a b.md", ["b.md"]),
            # reserved words
            ("if true; then cp a b.md; fi", ["b.md"]),
            ("while x; do cp a b.md; done", ["b.md"]),
            ("{ cp a b.md; }", ["b.md"]),
            ("! cp a b.md", ["b.md"]),
            ("for f in a; do cp a b/; done", ["b/"]),
            ("if x\nthen\n  cp a b.md\nfi", ["b.md"]),
            ("echo fi done then", []),
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

    def test_huge_or_deeply_nested_commands_are_cheap(self):
        # A hook that runs long fails open (the tool call times out), so pathological words must stay cheap.
        import time
        cases = {
            "20k open braces": "echo x > " + "{" * 20000,
            "20k groups": "echo x > " + "{a,b}" * 20000,
            "65 groups": "echo x > " + "{a,b}" * 65,
            "64 groups": "echo x > " + "{a,b}" * 64,
            "long word": "echo x > " + "a" * 200000,
            "deep $(": "echo " + "$(" * 5000 + "cp a b.md" + ")" * 5000,
            "deep (": "(" * 5000 + "cp a b.md" + ")" * 5000,
            "deep ${": "echo " + "${" * 5000 + " > a.md",
            "many heredocs": "cat <<E" * 3000 + "\nE\n" * 3000,
            "64 open heredocs a line, 1000 lines": ("cat " + "<<X " * 64 + "\n") * 1000,
            "distinct open heredocs": "".join("cat " + "".join(f"<<X{k}y{j} " for j in range(64)) + "\n" for k in range(1000)),
            "open heredocs in $(": "$(" * 31 + ("cat " + "<<X " * 64 + "\n") * 300,
            "open heredocs, lines with )": "echo $(" + ("cat " + "<<X " * 64 + "\nXy) a\n") * 500,
            "distinct heredocs, lines with )": "echo $(" + "".join(f"cat <<A{k} <<B{k}\n(A{k}) a\n" for k in range(3000)),
            "one delimiter, lines with )": "echo $(" + "".join(f"cat <<A <<A\n(A{k}) a\n" for k in range(3000)),
            "open (( x5000": "(( " * 5000,
            "open $(( x5000": "echo " + "$((" * 5000,
            "open $[ x5000": "echo " + "$[" * 5000,
            "open \"$( x5000": "echo " + '"$(' * 5000,
            "open quotes in $( x31": "echo " + '"$(echo "' * 31 + "x",
            "open quotes x5000": "echo " + "\"'" * 5000,
            "case patterns x5000": "x=$(case a in " + "a) b;; " * 5000 + "esac)",
        }
        for label, command in cases.items():
            with self.subTest(label=label):
                started = time.monotonic()
                found = gate.bash_targets(command)
                self.assertLess(time.monotonic() - started, 2.0)
                self.assertLessEqual(len(found), 256)
        self.assertEqual(gate.bash_targets("echo x > " + "{" * 5000), ["{" * 5000])  # over the limit: taken literally
        self.assertEqual(gate.bash_targets("echo x > " + "{a,b}" * 65), ["{a,b}" * 65])
        self.assertEqual(len(gate.bash_targets("echo x > " + "{a,b}" * 64)), 128)  # at the limit: expanded, capped
        self.assertEqual(gate.bash_targets("echo x > {" + "a" * 5000 + ",b}"), ["{" + "a" * 5000 + ",b}"])
        self.assertEqual(gate.bash_targets("cp a b.md; echo " + "$(" * 40 + ")" * 40), ["b.md"])  # deeper than the limit

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
        # An existing folder is itself a target, and so is each name the sources get in it.
        self.assertEqual(targets(command="cp a scripts/"),
                         [("scripts/", True), ("scripts/a", False), ("scripts/a/", False)])
        self.assertEqual(targets(command="cp -r /tmp/x/dir scripts"),
                         [("scripts/", True), ("scripts/dir", False), ("scripts/dir/", False)])
        self.assertEqual(targets(command="cp -t scripts a b"),
                         [("scripts/", True), ("scripts/a", False), ("scripts/a/", False),
                          ("scripts/b", False), ("scripts/b/", False)])
        self.assertEqual(targets(command="mv docs/ROUTING.md scripts"),
                         [("scripts/", True), ("scripts/ROUTING.md", False)])  # a file, so no folder form
        # A destination that is not there yet may be a folder about to be made: it is tried both ways.
        self.assertEqual(targets(command="cp -r a scripts/new"), [("scripts/new", False), ("scripts/new/", False)])
        self.assertEqual(targets(command="mv a docs/new"), [("docs/new", False), ("docs/new/", False)])
        self.assertEqual(targets(command="cp a docs/new/"), [("docs/new/", False)])  # written as a folder
        self.assertEqual(targets(command="mv a docs/ROUTING.md"), [("docs/ROUTING.md", True)])
        self.assertEqual(targets(command="echo x > docs/new"), [("docs/new", False)])  # a redirection is a file
        # Globs are matched against the folder the command runs in; no match leaves the name as written.
        self.assertEqual(targets(command="echo x > docs/ROUT*"), [("docs/ROUTING.md", True)])
        self.assertEqual(targets(command="echo x > docs/NOPE*"), [("docs/NOPE*", False)])
        self.assertEqual(targets(command="echo x > 'docs/ROUT*'"), [("docs/ROUT*", False)])
        self.assertEqual(targets(command="echo x > docs/{ROUTING,new}.md"),
                         [("docs/ROUTING.md", True), ("docs/new.md", False)])
        self.assertEqual(gate.targets({"cwd": str(root / "docs"), "tool_input": {"command": "echo x > R*"}}, root),
                         [("docs/ROUTING.md", True)])
        self.assertEqual(targets(file_path="docs/ROUT*"), [("docs/ROUT*", False)])  # a tool's path is literal
        self.assertEqual(targets(file_path="docs/new\0.md"), [("docs/new", False)])  # a C string ends at a NUL
        self.assertEqual(targets(file_path="\ud800"), [])  # cannot name a file: skipped, not an error
        self.assertEqual(targets(command="echo x > $'\\uD800' > docs/new.md"), [("docs/new.md", False)])
        self.assertEqual(gate.targets({"cwd": str(root), "tool_input": {"command": "echo x > \udc80\ud800 > docs/a.md"}},
                                      root), [("docs/a.md", False)])
        self.assertEqual(targets(command="tee docs/new"), [("docs/new", False)])
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
