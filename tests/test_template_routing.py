"""The template's two routing maps: `_meta/ROUTING-META.md` draws every `brain-*` skill and ships to every
brain; `docs/ROUTING.md` draws the template's own `template-*` skills and stays here. With both in place
the template lints clean and every generated block is current. Also: every planned skill exists, and every
skill the shipped gate rules name exists, since `lint` in a brain does not check the shipped rules.
"""
from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from typing import Set

from tests.helpers import TEMPLATE_ROOT, TempDirCase  # first: puts <template>/_meta on sys.path
from tests.test_shipped_skills import SHIPPED, TEMPLATE_ONLY
from brainlib import routing, skills

META = ("_meta", "ROUTING-META.md")
DOCS = ("docs", "ROUTING.md")
FINDING_SEVERITIES = ("BROKEN", "GAP", "ORPHAN")


def one_map(root: Path, parts) -> routing.Graph:
    """The graph of one map file on its own, as a brain reads `_meta/ROUTING-META.md` before adding its own."""
    graph = routing.Graph()
    name = "/".join(parts)
    routing.parse(root.joinpath(*parts).read_text(encoding="utf-8"), name, graph)
    return graph


def skill_nodes(graph: routing.Graph) -> Set[str]:
    return {node for node in graph.nodes if routing.is_skill_id(node)}


def present(prefix: str) -> Set[str]:
    return {s.name for s in skills.list_skills(TEMPLATE_ROOT) if s.name.startswith(prefix)}


def finding_lines(output: str):
    return [line for line in output.splitlines() if line.startswith(FINDING_SEVERITIES)]


class PlannedSkillsTest(unittest.TestCase):
    def test_every_planned_skill_exists(self):
        names = {s.name for s in skills.list_skills(TEMPLATE_ROOT)}
        self.assertEqual(sorted(set(SHIPPED + TEMPLATE_ONLY) - names), [])

    def test_every_skill_the_shipped_gate_rules_name_exists(self):
        # lint in a brain skips these (they name brain-* skills every brain holds), so they are held here
        data = json.loads((TEMPLATE_ROOT / "_meta" / "gates.json").read_text(encoding="utf-8"))
        named = {name for rule in data["rules"] for name in rule["skills"]}
        self.assertTrue(named)
        self.assertEqual(sorted(named - present("brain-")), [], "shipped rules may name only brain-* skills")


class MapsTest(unittest.TestCase):
    def test_every_brain_skill_drawn_in_meta(self):
        graph = one_map(TEMPLATE_ROOT, META)
        self.assertEqual(graph.problems, [])
        self.assertEqual(sorted(present("brain-") - skill_nodes(graph) - set(graph.not_drawn)), [])
        # the meta map ships: a node a brain has no skill for would be BROKEN in every brain
        self.assertEqual(sorted(n for n in skill_nodes(graph) if not n.startswith("brain-")), [])

    def test_every_brain_skill_reached_from_an_entry_in_meta(self):
        graph = one_map(TEMPLATE_ROOT, META)
        self.assertEqual(sorted(present("brain-") - routing.reachable(graph)), [])

    def test_every_template_skill_drawn_in_template_map(self):
        graph = one_map(TEMPLATE_ROOT, DOCS)
        self.assertEqual(graph.problems, [])
        self.assertEqual(sorted(present("template-") - skill_nodes(graph) - set(graph.not_drawn)), [])
        self.assertIn("not drawn", [line.strip("# ").lower() for line in
                                    (TEMPLATE_ROOT / "docs" / "ROUTING.md").read_text(encoding="utf-8").splitlines()
                                    if line.startswith("## ")])


class TemplateChecksTest(TempDirCase):
    def test_template_lint_clean(self):
        root = self.copy_template(with_local=False)
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(finding_lines(r.stdout), [], r.stdout)

    def test_template_sync_current(self):
        root = self.copy_template(with_local=False)
        r = self.run_brain(root, "routing", "sync", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_meta_map_lints_clean_in_a_brain(self):
        # a brain holds the meta map and the brain-* skills, never the template's own map or skills
        root = self.fake_brain(prefix="lab")
        (root / "docs").mkdir()
        shutil.copy2(str(TEMPLATE_ROOT / "_meta" / "skeleton" / "docs" / "ROUTING.md"), str(root / "docs" / "ROUTING.md"))
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(finding_lines(r.stdout), [], r.stdout)
        r = self.run_brain(root, "routing", "sync", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
