"""The skills the template ships (`brain-*`) and keeps for itself (`template-*`) follow the shared rules
for skills: lint finds nothing wrong with them, the body fits, the description says when to fire and when
not, the frontmatter is only `name` and `description`, and the generated block and the call-directly line
are in place.

Every planned skill that is present is checked. Each check runs on a temporary copy of the template that
holds a stub for every planned skill not written yet, so a "Does NOT ..., which is <sibling>" clause can
name a sibling that lands later; only findings about the real skills count.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Dict, List

from tests.helpers import TEMPLATE_ROOT, TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config, lint, routing, routing_sync, skills
from brainlib.report import BROKEN, GAP, ORPHAN

SHIPPED = ["brain-write-skill", "brain-write-script", "brain-write-practice", "brain-retro", "brain-upstream",
           "brain-sync", "brain-setup"]
TEMPLATE_ONLY = ["template-make-brain", "template-intake"]
PLANNED = SHIPPED + TEMPLATE_ONLY
EXPECTED = ["brain-write-skill"]  # the planned skills that must already exist
BODY_LIMIT = 110  # lines after the frontmatter, the generated block included
OWN_PREFIXES = ("brain-", "template-")


def present() -> Dict[str, skills.Skill]:
    """Every `brain-*` and `template-*` skill in the template's working tree, by name."""
    return {s.name: s for s in skills.list_skills(TEMPLATE_ROOT) if s.name.startswith(OWN_PREFIXES)}


def raw_description(path: Path) -> str:
    """The `description:` value exactly as the frontmatter writes it, before any unquoting."""
    lines = path.read_text(encoding="utf-8").split("\n")
    for line in lines[1:]:
        if line.rstrip() == "---":
            break
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    return ""


class ShippedSkillsTest(TempDirCase):
    def real_skills(self) -> Dict[str, skills.Skill]:
        found = present()
        missing = [name for name in EXPECTED if name not in found]
        self.assertEqual(missing, [], f"expected skills with no .claude/skills/<name>/SKILL.md: {missing}")
        return found

    def add_stubs(self, root: Path, planned: List[str], real: Dict[str, skills.Skill]) -> Path:
        """A stand-in SKILL.md under `root` for each of `planned` that is not written yet."""
        for name in planned:
            if name not in real:
                self.make_skill(root, name, "Stand-in for a planned skill that is not written yet.", "")
        return root

    def copy_with_stubs(self, real: Dict[str, skills.Skill]) -> Path:
        """A copy of the template, with stand-ins for the planned skills not written yet."""
        return self.add_stubs(self.copy_template(with_local=False), PLANNED, real)

    @staticmethod
    def listed(findings) -> str:
        return "\n".join(f"{f.severity:<6} {f.subject}: {f.message}" for f in findings)

    def test_expected_skills_exist(self):
        self.real_skills()

    def test_every_present_skill_is_planned(self):
        unplanned = sorted(set(self.real_skills()) - set(PLANNED))
        self.assertEqual(unplanned, [], "add each new brain-* or template-* skill to SHIPPED or TEMPLATE_ONLY")

    def test_lint_finds_nothing(self):
        real = self.real_skills()
        root = self.copy_with_stubs(real)
        findings = [f for f in lint.lint_skills(root, config.load(root))
                    if f.subject in real and f.severity in (BROKEN, GAP, ORPHAN)]
        self.assertEqual(findings, [], "\n" + self.listed(findings))

    def test_lint_finds_nothing_inside_a_brain(self):
        # A brain is where brain-* skills run: its own prefix, role "brain", no template-* skills.
        real = {name: s for name, s in self.real_skills().items() if name.startswith("brain-")}
        root = self.add_stubs(self.fake_brain(prefix="lab"), SHIPPED, real)
        findings = [f for f in lint.lint_skills(root, config.load(root))
                    if f.subject in real and f.severity in (BROKEN, GAP, ORPHAN)]
        self.assertEqual(findings, [], "\n" + self.listed(findings))

    def test_description_is_one_double_quoted_line_when_yaml_needs_it(self):
        # Unquoted, YAML refuses ": " in a value and ends it at " #", so the skill may not load as written.
        for name, skill in self.real_skills().items():
            description = skill.meta.get("description", "")
            if ": " not in description and " #" not in description:
                continue
            with self.subTest(skill=name):
                raw = raw_description(skill.path)
                self.assertTrue(len(raw) > 1 and raw.startswith('"') and raw.endswith('"'),
                                f"{name}: write the description on one line in double quotes")

    def test_body_fits(self):
        for name, skill in self.real_skills().items():
            with self.subTest(skill=name):
                lines = len(skill.body.splitlines())
                self.assertLessEqual(lines, BODY_LIMIT, f"{name} body is {lines} lines")

    def test_description_says_when_and_when_not(self):
        for name, skill in self.real_skills().items():
            description = skill.meta.get("description", "")
            with self.subTest(skill=name):
                self.assertIn("Use when", description)
                self.assertIn("Does NOT", description)

    def test_frontmatter_is_name_and_description_only(self):
        for name, skill in self.real_skills().items():
            with self.subTest(skill=name):
                self.assertEqual(sorted(skill.meta), ["description", "name"])

    def test_where_block_is_current_and_call_line_written(self):
        real = self.real_skills()
        root = self.copy_with_stubs(real)
        cfg = config.load(root)
        problems: List = []
        stale = routing_sync.sync(root, cfg, check=True, problems=problems)
        real_files = {f".claude/skills/{name}/SKILL.md" for name in real}
        self.assertEqual(sorted(set(stale) & real_files), [], "run _meta/brain routing sync and commit the blocks")
        self.assertEqual([f for f in problems if f.subject in real_files], [], "\n" + self.listed(problems))
        call_gaps = [f for f in routing.lint_routing(root, cfg, skills.list_skills(root))
                     if f.subject in real and routing.CALL in f.message]
        self.assertEqual(call_gaps, [], "\n" + self.listed(call_gaps))


if __name__ == "__main__":
    unittest.main()
