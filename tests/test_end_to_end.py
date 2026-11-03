"""The whole path once, the way a person meets it: a brain made by `new` is healthy, its gate refuses a skill
file until `brain-write-skill` has run and then lets it through, and its guard proves itself. Also the template
itself: it passes `doctor` once it has the pre-commit hook and `local/`, and its settings wire the gate.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.helpers import TEMPLATE_ROOT, TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import managed, skills


class EndToEndTest(TempDirCase):
    def hook_input(self, root: Path, tool: str, session: str = "end-to-end", **tool_input) -> str:
        event = "PostToolUse" if tool == "Skill" else "PreToolUse"
        return json.dumps({"session_id": session, "cwd": str(root), "hook_event_name": event,
                           "tool_name": tool, "tool_input": tool_input})

    def check_write(self, brain: Path, rel: str):
        return self.run_brain(brain, "gate", "check", stdin=self.hook_input(brain, "Write", file_path=str(brain / rel)))

    def test_new_brain_end_to_end(self):
        brain = self.make_brain(name="homelab", prefix="lab")

        doctor = self.run_brain(brain, "doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)

        # A skill file is refused until brain-write-skill has run in this session ...
        target = ".claude/skills/lab-x/SKILL.md"
        refused = self.check_write(brain, target)
        self.assertEqual(refused.returncode, 0, refused.stderr)  # a gate command never fails the tool call
        answer = json.loads(refused.stdout)["hookSpecificOutput"]
        self.assertEqual(answer["permissionDecision"], "deny")
        self.assertIn("brain-write-skill", answer["permissionDecisionReason"])
        self.assertIn(target, answer["permissionDecisionReason"])

        # ... and goes through once it has.
        recorded = self.run_brain(brain, "gate", "record",
                                  stdin=self.hook_input(brain, "Skill", skill="brain-write-skill"))
        self.assertEqual((recorded.returncode, recorded.stdout, recorded.stderr), (0, "", ""))
        allowed = self.check_write(brain, target)
        self.assertEqual((allowed.returncode, allowed.stdout, allowed.stderr), (0, "", ""))

        # Another session has run nothing.
        other = self.run_brain(brain, "gate", "check", stdin=self.hook_input(
            brain, "Write", session="another-session", file_path=str(brain / target)))
        self.assertEqual(json.loads(other.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

        selftest = self.run_brain(brain, "hook", "self-test")
        self.assertEqual(selftest.returncode, 0, selftest.stdout + selftest.stderr)

    def test_template_doctor_ok(self):
        template = self.copy_template(with_local=True)
        doctor = self.run_brain(template, "doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        lines = doctor.stdout.splitlines()
        for subject in ("template", "hook", "settings", "lint", "docs"):
            self.assertTrue(any(re.match(rf"ok\s+{subject}: ", line) for line in lines),
                            f"doctor has no ok line for '{subject}':\n{doctor.stdout}")

    def test_template_settings_are_the_managed_ones(self):
        written = json.loads((TEMPLATE_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(written, managed.merge_settings({}))

    def test_readme_names_every_skill_and_the_three_routes(self):
        readme = (TEMPLATE_ROOT / "README.md").read_text(encoding="utf-8")
        for skill in skills.list_skills(TEMPLATE_ROOT):
            if skill.name.startswith(("brain-", "template-")):
                self.assertIn(f"`{skill.name}`", readme, f"README.md does not name {skill.name}")
        for command in ("new", "adopt", "init"):
            self.assertRegex(readme, rf"_meta/brain {command}\b", f"README.md does not show `{command}`")
        for text in ("--add-dir", "Python 3.9", "unittest discover"):
            self.assertIn(text, readme)


if __name__ == "__main__":
    unittest.main()
