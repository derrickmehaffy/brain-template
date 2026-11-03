from __future__ import annotations

import ast
import json
import re
import unittest

from tests.helpers import TEMPLATE_ROOT, TempDirCase

from brainlib import managed, routing

SKELETON = TEMPLATE_ROOT / "_meta" / "skeleton"
MANAGED = TEMPLATE_ROOT / "_meta" / "managed"
KNOWN_PLACEHOLDERS = {"name", "prefix", "description"}

EXPECTED = {
    "CLAUDE.md", "README.md", "gitignore", "env.example", "claude-settings.json",
    "docs/README.md", "docs/ROUTING.md", "docs/CAPABILITIES.md", "docs/RETRO-LOG.md",
    "docs/UNCLASSIFIED-LOG.md", "docs/UPSTREAM.md", "docs/practices/README.md",
    "scripts/README.md", "scripts/tests/__init__.py",
}


def skeleton_files():
    return sorted(p.relative_to(SKELETON).as_posix() for p in SKELETON.rglob("*") if p.is_file())


def text_of(rel: str) -> str:
    return (SKELETON / rel).read_text(encoding="utf-8")


class SkeletonTest(TempDirCase):
    def test_skeleton_files_present_and_renamed(self):
        found = set(skeleton_files())
        self.assertLessEqual(EXPECTED, found, f"missing: {sorted(EXPECTED - found)}")
        for rel in found:
            parts = rel.split("/")
            self.assertFalse(any(part.startswith(".") for part in parts), f"{rel} is a dotfile or in a dot folder")
            self.assertNotIn(".claude/", rel)
        # `new` generates the practices index; the skeleton must not ship one.
        self.assertNotIn("docs/practices/INDEX.md", found)

    def test_skeleton_files_use_lf_and_end_in_a_newline(self):
        for rel in skeleton_files():
            data = (SKELETON / rel).read_bytes()
            self.assertNotIn(b"\r", data, f"{rel} has a carriage return")
            self.assertTrue(data.endswith(b"\n") or not data, f"{rel} has no final newline")

    def test_placeholders_are_the_known_three(self):
        seen = set()
        for rel in skeleton_files():
            seen.update(re.findall(r"\{\{(.*?)\}\}", text_of(rel)))
        self.assertLessEqual(seen, KNOWN_PLACEHOLDERS)
        self.assertIn("name", seen)
        self.assertIn("description", seen)

    def test_claude_md_shape(self):
        lines = text_of("CLAUDE.md").splitlines()
        self.assertEqual(lines[0], "# {{name}}")
        self.assertIn("{{description}}", lines)
        headings = [line for line in lines if line.startswith("#")]
        self.assertEqual(headings, ["# {{name}}", "## Folder map", "## Rules that bite"])
        # A placeholder line sits under each heading.
        for heading in ("## Folder map", "## Rules that bite"):
            after = lines[lines.index(heading) + 1:]
            body = [line for line in after[:3] if line.strip()]
            self.assertTrue(body and not body[0].startswith("#"), f"nothing under {heading}")

    def test_claude_md_takes_the_managed_block_at_the_top(self):
        out = managed.upsert(text_of("CLAUDE.md"), "md", managed.block_body(TEMPLATE_ROOT / "_meta", "md"))
        self.assertTrue(out.startswith(managed.MD_BEGIN + "\n"))
        self.assertIn(f"{managed.MD_END}\n\n# {{{{name}}}}\n", out)

    def test_readme_has_title_and_a_brain_paragraph(self):
        text = text_of("README.md")
        self.assertEqual(text.splitlines()[0], "# {{name}}")
        self.assertIn("brain", text)

    def test_one_line_files(self):
        self.assertEqual(text_of("gitignore"), "# The brain's own rules go below.\n")
        self.assertEqual(text_of("env.example"), "# Secret NAMES only. Values go in .env, which is ignored.\n")
        self.assertEqual(json.loads(text_of("claude-settings.json")), {})

    def test_docs_readme_lists_practices(self):
        self.assertIn("`practices/`", text_of("docs/README.md"))

    def test_log_tables_have_the_pinned_headers(self):
        pinned = {
            "docs/CAPABILITIES.md": "| System | Can | Cannot | Verified | How checked |",
            "docs/RETRO-LOG.md": "| Date | Skill | What went wrong | Fix | Status |",
            "docs/UNCLASSIFIED-LOG.md": "| Date | The work | Closest skill | What a skill would need | Seen before |",
        }
        for rel, header in pinned.items():
            with self.subTest(rel=rel):
                rows = [line for line in text_of(rel).splitlines() if line.startswith("|")]
                self.assertEqual(len(rows), 2, "a header row and its rule, nothing else")
                self.assertEqual(rows[0], header)
                self.assertRegex(rows[1], r"^\|( ?-{3,} ?\|){%d}$" % (header.count("|") - 1))

    def test_upstream_describes_its_entry_format_without_a_sample_entry(self):
        text = text_of("docs/UPSTREAM.md")
        for needle in ("<YYYY-MM-DD-slug>", "- template: <version>", "- files: <paths>",
                       "- status: open|landed <version>|declined: <reason>", "### What happened",
                       "### Proposed change"):
            self.assertIn(needle, text)
        # A sample would be read as an entry by `upstream list`: no line may start one.
        for line in text.splitlines():
            self.assertFalse(line.startswith("## "), line)
            self.assertFalse(line.startswith("- status:"), line)
            self.assertFalse(line.startswith("### "), line)

    def test_scripts_readme_is_three_rules(self):
        bullets = [line for line in text_of("scripts/README.md").splitlines() if line.startswith("- ")]
        self.assertEqual(len(bullets), 3)

    def test_scripts_tests_package_follows_the_harness_file_rule(self):
        # It lives under _meta/, so test_cli holds it to the same first-statement rule as the harness.
        body = ast.parse(text_of("scripts/tests/__init__.py")).body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        self.assertTrue(body and isinstance(body[0], ast.ImportFrom) and body[0].module == "__future__")

    def test_skeleton_routing_md_parses_clean(self):
        text = text_of("docs/ROUTING.md")
        graph = routing.Graph(nodes={}, edges=[], not_drawn={}, problems=[])
        routing.parse(text, "docs/ROUTING.md", graph)
        self.assertEqual(graph.problems, [])
        self.assertEqual((graph.nodes, graph.edges, graph.not_drawn), ({}, [], {}))
        lines = text.splitlines()
        self.assertEqual(lines[0], "# Routing map")
        self.assertIn("## Not drawn", lines)
        self.assertFalse([line for line in lines if line.lstrip().startswith("```")], "the skeleton draws nothing")
        rows = [line for line in lines if line.startswith("|")]
        self.assertEqual(len(rows), 2, "a header-only table")
        self.assertGreater(lines.index("## Not drawn"), 0)
        self.assertTrue(all(lines.index(row) > lines.index("## Not drawn") for row in rows))

    def test_routing_md_states_the_dialect(self):
        text = text_of("docs/ROUTING.md")
        for needle in ("-->", "-.->", "entry", "gate", "work", "optional", "decision", "state", "human",
                       "lowercase", "ROUTING-META.md"):
            self.assertIn(needle, text)

    def test_nothing_ships_a_home_path_or_a_secret_shape(self):
        paths = [SKELETON / rel for rel in skeleton_files()] + sorted(MANAGED.iterdir())
        for path in paths:
            data = path.read_text(encoding="utf-8")
            self.assertNotRegex(data, r"/(home|Users)/[A-Za-z]", str(path))
            self.assertNotRegex(data, r"-----BEGIN", str(path))

    def test_managed_files_exist_and_hold_the_spec_content(self):
        gi = (MANAGED / "gitignore.block").read_text(encoding="utf-8").splitlines()
        self.assertEqual(gi, [
            "/*", "!/.gitignore", "!/brain.json", "!/CLAUDE.md", "!/README.md", "!/.env.example", "!/.claude/",
            "!/_meta/", "!/docs/", "!/scripts/", ".env", ".env.*", "!.env.example", "/.claude/settings.local.json",
            "__pycache__/", "*.pyc", ".DS_Store",
        ])
        md = (MANAGED / "CLAUDE.block.md").read_text(encoding="utf-8")
        flat = " ".join(md.split())  # the spec wraps at 100 columns; wrapping is not the content
        for needle in (
            "This folder is a brain (`brain.json`)", "**Call skills, never read them**",
            "docs/ROUTING.md", "A write blocked by the skill gate", "docs/CAPABILITIES.md",
            "_meta/brain practices search <terms>", "`brain-write-script`", "`brain-retro`",
            "Project folders are not the brain", "`brain-upstream`", "only the `brain-*` ones know",
            "Secrets live in `.env` (ignored). Never read, print or commit values.",
            "Secret names: `_meta/brain env-sync --list`.",
        ):
            self.assertIn(needle, flat)
        bullets = [line for line in md.splitlines() if line.startswith("- ")]
        self.assertEqual(len(bullets), 10)


if __name__ == "__main__":
    unittest.main()
