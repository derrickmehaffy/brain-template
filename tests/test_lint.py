from __future__ import annotations

import re
import textwrap
import unittest
from pathlib import Path

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config, lint, skills
from brainlib.report import BROKEN, GAP, ORPHAN, Finding

SUMMARY = re.compile(r"^lint: (\d+) broken, (\d+) gap, (\d+) orphan$")


def clean_description(sibling: str) -> str:
    return f"Does X. Use when Y. Does NOT do Z, which is {sibling}."


def clean_body(extra_lines: int = 0, done: bool = True) -> str:
    """A body that cites its reference, has a Done when section and is `extra_lines` longer than its base."""
    lines = ["Read `references/r.md` first.", ""]
    if done:
        lines += ["## Done when", "", "- the thing works"]
    return "\n".join(lines + ["- more"] * extra_lines)


class LintBase(TempDirCase):
    def write_raw(self, root: Path, folder: str, text: str) -> Path:
        path = root / ".claude" / "skills" / folder / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def add_clean(self, root: Path, name: str, sibling: str, description=None, body=None) -> Path:
        """A skill that lints clean: a sibling-naming Does NOT, a Done when, a cited reference that exists."""
        path = self.make_skill(
            root, name, description if description is not None else clean_description(sibling),
            body if body is not None else clean_body(),
        )
        ref = path.parent / "references" / "r.md"
        ref.parent.mkdir(exist_ok=True)
        ref.write_text("detail\n", encoding="utf-8")
        return path

    def folded_description_skill(self, root: Path, total_length: int) -> None:
        """lab-a whose `description: >-` is exactly `total_length` characters once folded."""
        base = clean_description("lab-b")
        filler_length = total_length - len(base) - 1
        words = filler_length // 60
        while filler_length - 60 * words < 1:
            words -= 1
        filler = " ".join(["x" * 59] * words + ["x" * (filler_length - 60 * words)])
        text = base + " " + filler
        lines = textwrap.wrap(text, 70)
        self.assertEqual((len(text), " ".join(lines)), (total_length, text))
        self.write_raw(root, "lab-a", "---\nname: lab-a\ndescription: >-\n" + "".join(f"  {l}\n" for l in lines)
                       + "---\n" + clean_body() + "\n")

    def brain_with_pair(self, **kwargs) -> Path:
        root = self.fake_brain(**kwargs)
        self.add_clean(root, "lab-a", "lab-b")
        self.add_clean(root, "lab-b", "lab-a")
        return root

    def lint_skills(self, root: Path) -> list:
        return lint.lint_skills(root, config.load(root))

    @staticmethod
    def shape(findings) -> list:
        return [(f.severity, f.subject) for f in findings]

    def assert_summary_matches_lines(self, stdout: str) -> None:
        lines = stdout.splitlines()
        match = SUMMARY.match(lines[-1])
        self.assertIsNotNone(match, f"last line is not the summary: {lines[-1]!r}")
        printed = tuple(sum(1 for line in lines[:-1] if line.startswith(sev + " ")) for sev in (BROKEN, GAP, ORPHAN))
        self.assertEqual(tuple(int(n) for n in match.groups()), printed)


class LintSkillsTest(LintBase):
    def test_clean_skill_has_no_findings(self):
        root = self.brain_with_pair()
        self.assertEqual(self.lint_skills(root), [])

    def test_no_skills_folder_has_no_findings(self):
        self.assertEqual(self.lint_skills(self.fake_brain()), [])

    def test_broken_cases(self):
        def raw(folder, text):
            return lambda root: self.write_raw(root, folder, text)

        long_base = clean_description("lab-b")
        cases = {
            "missing name": (
                raw("lab-a", f"---\ndescription: {clean_description('lab-b')}\n---\n{clean_body()}\n"),
                "lab-a", "no name"),
            "missing description": (
                raw("lab-a", f"---\nname: lab-a\n---\n{clean_body()}\n"),
                "lab-a", "no description"),
            "name differs from folder": (
                raw("lab-a", f"---\nname: lab-x\ndescription: {clean_description('lab-b')}\n---\n{clean_body()}\n"),
                "lab-a", "lab-x"),
            "duplicate frontmatter name": (
                raw("lab-b", f"---\nname: lab-a\ndescription: {clean_description('lab-a')}\n---\n{clean_body()}\n"),
                "lab-b", "also declared by lab-a"),
            "SKILL.md nested deeper": (
                lambda root: self.write_raw(root, "lab-a/sub", "---\nname: sub\ndescription: x\n---\n"),
                "lab-a", "sub/SKILL.md"),
            "description of 1025 characters": (
                lambda root: self.add_clean(root, "lab-a", "lab-b",
                                            description=long_base + " " + "x" * (1024 - len(long_base))),
                "lab-a", "1025"),
            "cited reference is missing": (
                lambda root: self.add_clean(root, "lab-a", "lab-b",
                                            body=clean_body() + "\n\nAlso read `references/missing.md`."),
                "lab-a", "references/missing.md"),
            "Does NOT names a skill that does not exist": (
                lambda root: self.add_clean(root, "lab-a", "lab-ghost"),
                "lab-a", "lab-ghost"),
        }
        for label, (mutate, subject, fragment) in cases.items():
            with self.subTest(label):
                root = self.brain_with_pair()
                mutate(root)
                findings = self.lint_skills(root)
                self.assertEqual(self.shape(findings), [(BROKEN, subject)], findings)
                self.assertIn(fragment, findings[0].message)

    def test_description_limit_is_inclusive(self):
        root = self.brain_with_pair()
        base = clean_description("lab-b")
        self.add_clean(root, "lab-a", "lab-b", description=base + " " + "x" * (1023 - len(base)))
        self.assertEqual(self.lint_skills(root), [])

    def test_folded_description_over_the_limit_is_broken(self):
        for total, expected in ((1024, []), (1025, [(BROKEN, "lab-a")])):
            with self.subTest(total):
                root = self.brain_with_pair()
                self.folded_description_skill(root, total)
                findings = self.lint_skills(root)
                self.assertEqual(self.shape(findings), expected, findings)
                if expected:
                    self.assertIn("1025", findings[0].message)

    def test_block_and_multi_line_quoted_descriptions_are_read_whole(self):
        text = "Does X. Use when Y.\n  Does NOT do Z, which is lab-b."
        forms = {
            "folded": f"description: >\n  {text}\n",
            "folded, stripped": f"description: >-\n  {text}\n",
            "literal": f"description: |\n  {text}\n",
            "double quoted": f'description: "{text}"\n',
            "single quoted": f"description: '{text}'\n",
        }
        for label, line in forms.items():
            with self.subTest(label):
                root = self.brain_with_pair()
                self.write_raw(root, "lab-a", f"---\nname: lab-a\n{line}---\n{clean_body()}\n")
                self.assertEqual(self.lint_skills(root), [])

    def test_block_description_naming_a_missing_skill_is_broken(self):
        root = self.brain_with_pair()
        self.write_raw(root, "lab-a", "---\nname: lab-a\ndescription: >-\n  Does X. Use when Y.\n"
                       "  Does NOT do Z, which is lab-ghost.\n---\n" + clean_body() + "\n")
        findings = self.lint_skills(root)
        self.assertEqual(self.shape(findings), [(BROKEN, "lab-a")])
        self.assertIn("lab-ghost", findings[0].message)

    def test_cited_path_found_at_brain_root_is_fine(self):
        root = self.brain_with_pair()
        self.add_clean(root, "lab-a", "lab-b", body=clean_body() + "\n\nRun `scripts/common/x.py`.")
        findings = self.lint_skills(root)
        self.assertEqual(self.shape(findings), [(BROKEN, "lab-a")])
        self.assertIn("scripts/common/x.py", findings[0].message)
        script = root / "scripts" / "common" / "x.py"
        script.parent.mkdir(parents=True)
        script.write_text("", encoding="utf-8")
        self.assertEqual(self.lint_skills(root), [])

    def test_cited_path_found_in_skill_folder_is_fine(self):
        root = self.brain_with_pair()
        extra = root / ".claude" / "skills" / "lab-a" / "scripts" / "run.sh"
        extra.parent.mkdir(parents=True)
        extra.write_text("", encoding="utf-8")
        self.add_clean(root, "lab-a", "lab-b", body=clean_body() + "\n\nRun `scripts/run.sh`.")
        self.assertEqual(self.lint_skills(root), [])

    def test_trailing_punctuation_is_not_part_of_the_path(self):
        root = self.brain_with_pair()
        self.add_clean(root, "lab-a", "lab-b", body=clean_body() + "\n\n(see references/r.md), then references/r.md.")
        self.assertEqual(self.lint_skills(root), [])

    def test_paths_with_another_directory_in_front_are_not_checked(self):
        root = self.brain_with_pair()
        self.add_clean(root, "lab-a", "lab-b",
                       body=clean_body() + "\n\nSee docs/references/nope.md and ../scripts/nope.py.")
        self.assertEqual(self.lint_skills(root), [])

    def test_placeholder_paths_not_checked(self):
        root = self.brain_with_pair()
        self.add_clean(root, "lab-a", "lab-b", body=clean_body() + (
            "\n\nPut output in `scripts/<system>/`, read `references/guide-<topic>.md` and "
            "`scripts/common/<name>.py`, see `scripts/*.py` and `references/{a,b}.md`."))
        self.assertEqual(self.lint_skills(root), [])

    def test_gap_cases(self):
        lines_151 = clean_body(extra_lines=151 - len(clean_body().splitlines()))
        self.assertEqual(len(lines_151.splitlines()), 151)
        cases = {
            "no Does NOT clause": (
                lambda root: self.add_clean(root, "lab-a", "lab-b", description="Does X. Use when Y."),
                "lab-a", "Does NOT"),
            "Does NOT names no skill": (
                lambda root: self.add_clean(root, "lab-a", "lab-b", description="Does X. Does NOT do Z."),
                "lab-a", "Does NOT"),
            "no Done when section": (
                lambda root: self.add_clean(root, "lab-a", "lab-b", body=clean_body(done=False)),
                "lab-a", "Done when"),
            "body of 151 lines": (
                lambda root: self.add_clean(root, "lab-a", "lab-b", body=lines_151),
                "lab-a", "151"),
            "skill without the brain's prefix": (
                lambda root: self.add_clean(root, "other-x", "lab-b"),
                "other-x", "'lab-'"),
        }
        for label, (mutate, subject, fragment) in cases.items():
            with self.subTest(label):
                root = self.brain_with_pair()
                mutate(root)
                findings = self.lint_skills(root)
                self.assertEqual(self.shape(findings), [(GAP, subject)], findings)
                self.assertIn(fragment, findings[0].message)

    def test_body_length_boundary_is_150_lines(self):
        root = self.brain_with_pair()
        body = clean_body(extra_lines=150 - len(clean_body().splitlines()))
        self.assertEqual(len(body.splitlines()), 150)
        self.add_clean(root, "lab-a", "lab-b", body=body)
        self.assertEqual(self.lint_skills(root), [])

    def test_body_length_ignores_frontmatter(self):
        root = self.brain_with_pair()
        self.write_raw(root, "lab-a", "---\nname: lab-a\ndescription: " + clean_description("lab-b") + "\n" +
                       "\n".join(f"extra{i}: v" for i in range(160)) + "\n---\n" + clean_body() + "\n")
        self.assertEqual(self.lint_skills(root), [])

    def test_orphan_reference(self):
        root = self.brain_with_pair()
        unused = root / ".claude" / "skills" / "lab-a" / "references" / "unused.md"
        unused.write_text("never cited\n", encoding="utf-8")
        findings = self.lint_skills(root)
        self.assertEqual(self.shape(findings), [(ORPHAN, "lab-a")])
        self.assertIn("references/unused.md", findings[0].message)

    def test_orphan_check_walks_subfolders_skips_dotfiles_and_honours_folder_cites(self):
        root = self.brain_with_pair()
        refs = root / ".claude" / "skills" / "lab-a" / "references"
        for rel in ("deep/orphan.md", "guides/one.md", "guides/two.md", ".DS_Store", "deep/.hidden"):
            (refs / rel).parent.mkdir(parents=True, exist_ok=True)
            (refs / rel).write_text("x\n", encoding="utf-8")
        self.add_clean(root, "lab-a", "lab-b", body=clean_body() + "\n\nRead everything under `references/guides/`.")
        findings = self.lint_skills(root)
        self.assertEqual(self.shape(findings), [(ORPHAN, "lab-a")])
        self.assertIn("references/deep/orphan.md", findings[0].message)

    def test_bare_references_folder_mention_does_not_cite_everything(self):
        root = self.brain_with_pair()
        (root / ".claude" / "skills" / "lab-a" / "references" / "unused.md").write_text("x\n", encoding="utf-8")
        self.add_clean(root, "lab-a", "lab-b", body=clean_body() + "\n\nDetail lives in references/.")
        self.assertEqual(self.shape(self.lint_skills(root)), [(ORPHAN, "lab-a")])

    def test_template_tokens_ignored_in_brain(self):
        root = self.brain_with_pair()
        self.add_clean(root, "lab-a", "lab-b",
                       description="Does X. Does NOT do Z, which is template-intake, nor W, which is lab-b.")
        self.assertEqual(self.lint_skills(root), [])

    def test_prose_tokens_after_does_not_never_raise_broken(self):
        # "brain-wide" has this template's own prefix but is not a skill name.
        root = self.brain_with_pair()
        self.add_clean(root, "lab-a", "lab-b",
                       description="Does X. Use when Y. Does NOT make brain-wide changes, which is lab-b.")
        self.assertEqual(self.lint_skills(root), [])
        self.add_clean(root, "lab-a", "lab-b",
                       description="Does X. Does NOT touch brain-dump or lab-ghost; ask lab-b.")
        self.assertEqual(self.lint_skills(root), [])

    def test_only_a_named_skill_introduced_by_which_is_or_that_is_can_be_broken(self):
        cases = {
            "which is": "Does NOT make brain-wide changes or a brain-dump, which is lab-ghost.",
            "that is": "Does NOT make brain-wide changes, that is lab-ghost.",
            "backticks": "Does NOT do Z, which is `lab-ghost`.",
            "list with or": "Does NOT do Z, which is lab-b or lab-ghost.",
            "list with commas and backticks": "Does NOT do Z, which is `lab-b`, `lab-ghost` and `lab-a`.",
            "list with and": "Does NOT do Z, that is lab-ghost and lab-b.",
        }
        for label, clause in cases.items():
            with self.subTest(label):
                root = self.brain_with_pair()
                self.add_clean(root, "lab-a", "lab-b", description=f"Does X. {clause}")
                findings = self.lint_skills(root)
                self.assertEqual(self.shape(findings), [(BROKEN, "lab-a")], findings)
                self.assertIn("lab-ghost", findings[0].message)
                self.assertNotIn("brain-", findings[0].message)

    def test_names_without_which_is_are_not_checked_for_existence(self):
        root = self.brain_with_pair()
        self.add_clean(root, "lab-a", "lab-b",
                       description="Pairs with lab-ghost. Does NOT replace lab-b; unlike lab-ghost it is small.")
        self.assertEqual(self.lint_skills(root), [])

    def test_does_not_clause_needs_an_existing_skill_other_than_the_skill_itself(self):
        cases = {
            "names only itself": "Does X. Does NOT do Z, which is lab-a.",
            "names only prose tokens": "Does X. Does NOT make brain-wide changes.",
            "names only a skill that is not here and has no introducer": "Does X. Does NOT replace lab-ghost.",
        }
        for label, description in cases.items():
            with self.subTest(label):
                root = self.brain_with_pair()
                self.add_clean(root, "lab-a", "lab-b", description=description)
                findings = self.lint_skills(root)
                self.assertEqual(self.shape(findings), [(GAP, "lab-a")], findings)

    def test_naming_a_sibling_without_which_is_satisfies_the_clause(self):
        root = self.brain_with_pair()
        self.add_clean(root, "lab-a", "lab-b", description="Does X. Does NOT replace lab-b.")
        self.assertEqual(self.lint_skills(root), [])

    def test_template_tokens_checked_in_the_template(self):
        root = self.fake_brain(prefix="lab", role="template")
        self.add_clean(root, "template-intake", "template-ghost")
        self.add_clean(root, "template-other", "template-intake")
        findings = self.lint_skills(root)
        self.assertEqual(self.shape(findings), [(BROKEN, "template-intake")])
        self.assertIn("template-ghost", findings[0].message)

    def test_brain_skills_are_named_everywhere(self):
        root = self.brain_with_pair()
        self.add_clean(root, "brain-tool", "lab-a")
        self.add_clean(root, "lab-a", "brain-tool")
        self.add_clean(root, "lab-b", "brain-missing")
        findings = self.lint_skills(root)
        self.assertEqual(self.shape(findings), [(BROKEN, "lab-b")])
        self.assertIn("brain-missing", findings[0].message)

    def test_adopted_style_skill_gaps_not_broken(self):
        root = self.fake_brain()
        self.make_skill(root, "se2-idea", "Turn a rough idea into a spec.",
                        "\n".join(f"line {i}" for i in range(200)))
        findings = self.lint_skills(root)
        self.assertEqual(self.shape(findings), [(GAP, "se2-idea")] * 4)
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for fragment in ("'lab-'", "Does NOT", "Done when", "200"):
            self.assertTrue(any(l.startswith("GAP    se2-idea:") and fragment in l for l in r.stdout.splitlines()),
                            f"no GAP line with {fragment!r} in:\n{r.stdout}")

    def test_adopted_skill_with_extra_frontmatter_keys(self):
        root = self.fake_brain()
        self.add_clean(root, "lab-b", "lab-a")
        self.write_raw(root, "lab-a", "---\nname: lab-a\ndescription: \"Does X. Does NOT do Z, which is lab-b.\"\n"
                       "allowed-tools: [Read, Grep]\nmodel: sonnet\n---\n## Done when\n\n- ok\n")
        self.assertEqual(self.lint_skills(root), [])

    def test_findings_for_several_skills_come_out_in_skill_order(self):
        root = self.brain_with_pair()
        self.add_clean(root, "lab-b", "lab-a", description="Does X.")
        self.add_clean(root, "lab-a", "lab-b", description="Does X.")
        self.assertEqual(self.shape(self.lint_skills(root)), [(GAP, "lab-a"), (GAP, "lab-b")])


class ExtraChecksTest(LintBase):
    def test_extra_checks_get_root_config_and_skills_and_only_all_findings_runs_them(self):
        root = self.brain_with_pair()
        seen = []

        def extra(root_arg, cfg, found):
            seen.append((root_arg, cfg.prefix, [s.name for s in found]))
            return [Finding(GAP, "map", "extra check ran")]

        # Alone in the list, so the checks other modules register (routing, route, gate) add nothing here.
        registered = list(lint.EXTRA_CHECKS)
        self.addCleanup(lint.EXTRA_CHECKS.__setitem__, slice(None), registered)
        lint.EXTRA_CHECKS[:] = [extra]
        cfg = config.load(root)
        self.assertEqual(lint.lint_skills(root, cfg), [])
        self.assertEqual(seen, [])
        self.assertEqual(lint.all_findings(root, cfg), [Finding(GAP, "map", "extra check ran")])
        self.assertEqual(seen, [(root, "lab", ["lab-a", "lab-b"])])


class LintCommandTest(LintBase):
    def test_exit_codes_and_summary(self):
        # BROKEN fails the run.
        root = self.brain_with_pair()
        self.add_clean(root, "lab-a", "lab-b", body=clean_body() + "\n\nAlso read `references/missing.md`.")
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(any(l.startswith("BROKEN lab-a: ") and "references/missing.md" in l
                            for l in r.stdout.splitlines()), r.stdout)
        self.assert_summary_matches_lines(r.stdout)

        # GAP alone does not.
        root = self.brain_with_pair()
        self.add_clean(root, "lab-a", "lab-b", description="Does X. Use when Y.")
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any(l.startswith("GAP    lab-a: ") for l in r.stdout.splitlines()), r.stdout)
        self.assert_summary_matches_lines(r.stdout)

    def test_orphan_does_not_fail_the_run(self):
        root = self.brain_with_pair()
        (root / ".claude" / "skills" / "lab-a" / "references" / "unused.md").write_text("x\n", encoding="utf-8")
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any(l.startswith("ORPHAN lab-a: ") for l in r.stdout.splitlines()), r.stdout)
        self.assert_summary_matches_lines(r.stdout)

    def test_summary_is_the_last_line_even_without_findings(self):
        root = self.fake_brain()
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assert_summary_matches_lines(r.stdout)

    def test_missing_brain_json_is_a_refusal(self):
        root = self.fake_brain()
        (root / "brain.json").unlink()
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 1)
        self.assertIn("brain.json", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_lint_is_listed_in_help(self):
        r = self.run_brain(self.fake_brain(), "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("lint", r.stdout)
        self.assertIn("check skills and the routing map", r.stdout)

    def test_lint_leaves_the_brain_untouched(self):
        root = self.brain_with_pair()
        before = self.snapshot(root)
        self.run_brain(root, "lint")
        self.assertEqual(self.snapshot(root), before)


class ParseFrontmatterTest(unittest.TestCase):
    def parse(self, text):
        return skills.parse_frontmatter(text)

    def test_reads_single_line_pairs_and_returns_the_body(self):
        meta, body = self.parse("---\nname: lab-a\ndescription: Does X. Use when Y.\n---\n# Title\n\ntext\n")
        self.assertEqual(meta, {"name": "lab-a", "description": "Does X. Use when Y."})
        self.assertEqual(body, "# Title\n\ntext\n")

    def test_optional_quotes_are_stripped(self):
        meta, _ = self.parse("---\na: \"double: quoted\"\nb: 'single'\nc: \"unterminated\nd: it's\n---\n")
        self.assertEqual(meta, {"a": "double: quoted", "b": "single", "c": "\"unterminated", "d": "it's"})

    def test_value_may_contain_colons_and_brackets_are_kept_raw(self):
        meta, _ = self.parse("---\ndescription: Use when: a, b\ntools: [Read, Grep]\n---\n")
        self.assertEqual(meta, {"description": "Use when: a, b", "tools": "[Read, Grep]"})

    def test_no_frontmatter_leaves_the_text_alone(self):
        text = "# Just a title\n\nname: not frontmatter\n"
        self.assertEqual(self.parse(text), ({}, text))
        self.assertEqual(self.parse(""), ({}, ""))

    def test_unterminated_frontmatter_is_not_frontmatter(self):
        text = "---\nname: lab-a\nno closing line\n"
        self.assertEqual(self.parse(text), ({}, text))

    def test_crlf_and_bom(self):
        meta, body = self.parse("﻿---\r\nname: lab-a\r\ndescription: x\r\n---\r\nbody\r\n")
        self.assertEqual(meta, {"name": "lab-a", "description": "x"})
        self.assertEqual(body, "body\r\n")

    def test_nested_mappings_comments_and_blank_lines_are_ignored(self):
        meta, _ = self.parse("---\n# comment\nname: lab-a\n\nmetadata:\n  author: someone\n  tags: [a]\nkey_2-x: v\n---\n")
        self.assertEqual(meta, {"name": "lab-a", "metadata": "", "key_2-x": "v"})

    def test_folded_block_scalar_joins_lines_with_spaces(self):
        meta, body = self.parse("---\nname: lab-a\ndescription: >\n  Does X. Use when Y.\n  Does NOT do Z.\n"
                                "model: sonnet\n---\nbody\n")
        self.assertEqual(meta, {"name": "lab-a", "description": "Does X. Use when Y. Does NOT do Z.\n",
                                "model": "sonnet"})
        self.assertEqual(body, "body\n")

    def test_folded_strip_marker_drops_the_final_newline(self):
        meta, _ = self.parse("---\ndescription: >-\n  Does X.\n  Does NOT do Z.\n---\n")
        self.assertEqual(meta, {"description": "Does X. Does NOT do Z."})

    def test_literal_block_scalar_keeps_newlines(self):
        meta, _ = self.parse("---\ndescription: |\n  line one\n    indented more\n  line three\nname: n\n---\n")
        self.assertEqual(meta, {"description": "line one\n  indented more\nline three\n", "name": "n"})
        meta, _ = self.parse("---\ndescription: |-\n  line one\n  line two\n---\n")
        self.assertEqual(meta, {"description": "line one\nline two"})

    def test_block_scalar_blank_lines_and_keep_marker(self):
        meta, _ = self.parse("---\na: >-\n  one\n\n  two\nb: |+\n  keep\n\n---\n")
        self.assertEqual(meta, {"a": "one\ntwo", "b": "keep\n\n"})

    def test_block_scalar_ends_at_the_next_unindented_line(self):
        meta, _ = self.parse("---\na: >-\n  one\n  two\n# comment\nb: x\n---\n")
        self.assertEqual(meta, {"a": "one two", "b": "x"})

    def test_empty_block_scalar_and_header_comment(self):
        meta, _ = self.parse("---\na: >-\nb: |  # note\n  text\n---\n")
        self.assertEqual(meta, {"a": "", "b": "text\n"})

    def test_block_scalar_with_crlf(self):
        meta, _ = self.parse("---\r\ndescription: >-\r\n  one\r\n  two\r\nname: n\r\n---\r\n")
        self.assertEqual(meta, {"description": "one two", "name": "n"})

    def test_multi_line_double_quoted_value(self):
        meta, _ = self.parse('---\ndescription: "Does X.\n  Use when Y.\n  Does NOT do Z."\nname: n\n---\n')
        self.assertEqual(meta, {"description": "Does X. Use when Y. Does NOT do Z.", "name": "n"})

    def test_multi_line_single_quoted_value_and_blank_line(self):
        meta, _ = self.parse("---\ndescription: 'Does X.\n\n  Use when Y.'\n---\n")
        self.assertEqual(meta, {"description": "Does X.\nUse when Y."})

    def test_escaped_quote_at_a_line_end_does_not_close_the_value(self):
        meta, _ = self.parse('---\na: "one \\"\n  two"\nb: x\n---\n')
        self.assertEqual(meta, {"a": 'one \\" two', "b": "x"})

    def test_quoted_value_that_never_closes_swallows_nothing(self):
        meta, _ = self.parse('---\na: "never closes\nb: x\nc: y\n---\n')
        self.assertEqual(meta, {"a": '"never closes', "b": "x", "c": "y"})

    def test_doubled_single_quote_does_not_close_a_single_quoted_value(self):
        meta, _ = self.parse("---\na: 'it''s\n  more'\nb: x\n---\n")
        self.assertEqual(meta, {"a": "it''s more", "b": "x"})

    def test_quoted_value_followed_by_a_comment_swallows_nothing(self):
        meta, _ = self.parse('---\na: "quoted" # note\nb: "x"\nc: \'y\'\n---\n')
        self.assertEqual(meta, {"a": "quoted", "b": "x", "c": "y"})

    def test_quoted_value_with_trailing_text_is_kept_raw_and_swallows_nothing(self):
        meta, _ = self.parse('---\na: "open\nb: "x" tail\nc: y\n---\n')
        self.assertEqual(meta, {"a": '"open', "b": '"x" tail', "c": "y"})

    def test_empty_value_and_last_duplicate_wins(self):
        meta, _ = self.parse("---\nname:\ndescription: one\ndescription: two\n---\n")
        self.assertEqual(meta, {"name": "", "description": "two"})

    def test_unusual_line_separators_in_a_value_do_not_split_the_line(self):
        meta, _ = self.parse("---\ndescription: a b\x85c\n---\n")
        self.assertEqual(meta, {"description": "a b\x85c"})

    def test_a_rule_line_in_the_body_is_not_a_second_frontmatter(self):
        meta, body = self.parse("---\nname: x\n---\nbody\n---\nmore\n")
        self.assertEqual((meta, body), ({"name": "x"}, "body\n---\nmore\n"))


class SkillListingTest(LintBase):
    def test_list_skills_returns_sorted_folders_that_hold_a_skill_md(self):
        root = self.fake_brain()
        self.make_skill(root, "lab-b", "Second.", "body b")
        self.make_skill(root, "lab-a", "First.", "body a")
        (root / ".claude" / "skills" / "no-skill-md").mkdir()
        (root / ".claude" / "skills" / "loose-file.md").write_text("x", encoding="utf-8")
        listed = skills.list_skills(root)
        self.assertEqual([s.name for s in listed], ["lab-a", "lab-b"])
        first = listed[0]
        self.assertEqual(first.folder, root / ".claude" / "skills" / "lab-a")
        self.assertEqual(first.path, first.folder / "SKILL.md")
        self.assertEqual(first.meta, {"name": "lab-a", "description": "First."})
        self.assertEqual(first.body, "body a\n")

    def test_skill_name_is_the_folder_even_when_the_frontmatter_disagrees(self):
        root = self.fake_brain()
        self.write_raw(root, "lab-a", "---\nname: lab-x\ndescription: d\n---\n")
        (skill,) = skills.list_skills(root)
        self.assertEqual((skill.name, skill.meta["name"]), ("lab-a", "lab-x"))

    def test_list_skills_without_a_skills_folder(self):
        self.assertEqual(skills.list_skills(self.fake_brain()), [])

    def test_unreadable_bytes_do_not_crash(self):
        root = self.fake_brain()
        path = self.make_skill(root, "lab-a", "d", "body")
        path.write_bytes(b"---\nname: lab-a\ndescription: caf\xe9\n---\nbody\n")
        (skill,) = skills.list_skills(root)
        self.assertEqual(skill.meta["name"], "lab-a")

    def test_deep_skill_files(self):
        root = self.fake_brain()
        self.make_skill(root, "lab-a", "d", "b")
        deep = self.write_raw(root, "lab-a/sub", "x")
        deeper = self.write_raw(root, "lab-c/references/inner", "x")
        self.assertEqual(skills.deep_skill_files(root), [deep, deeper])
        self.assertEqual(skills.deep_skill_files(self.fake_brain()), [])


class NamingTest(TempDirCase):
    def cfg(self, prefix="lab", role="brain"):
        return config.load(self.fake_brain(prefix=prefix, role=role))

    def test_skill_prefixes(self):
        self.assertEqual(skills.skill_prefixes(self.cfg()), {"brain", "lab"})
        self.assertEqual(skills.skill_prefixes(self.cfg(role="template")), {"brain", "lab", "template"})
        self.assertEqual(skills.skill_prefixes(self.cfg(prefix="")), {"brain"})

    def test_named_skills(self):
        prefixes = {"brain", "lab"}
        text = "which is lab-a, or `brain-write-practice`; not template-x, nor labx-y, nor Lab-q. Also (lab-b)."
        self.assertEqual(skills.named_skills(text, prefixes), ["lab-a", "brain-write-practice", "lab-b"])

    def test_named_skills_takes_the_whole_hyphenated_token_once(self):
        self.assertEqual(skills.named_skills("lab-a-b-2, lab-a-b-2 and lab-a.", {"lab"}), ["lab-a-b-2", "lab-a"])

    def test_named_skills_ignores_paths_and_file_names(self):
        text = "see docs/lab-notes, lab-notes.md, ./lab-x, lab-a/SKILL.md, lab-a-b.md, lab_a-b and lab-"
        self.assertEqual(skills.named_skills(text, {"lab"}), [])

    def test_named_skills_with_no_prefixes(self):
        self.assertEqual(skills.named_skills("lab-a", set()), [])

    def test_introduced_skills(self):
        prefixes = {"brain", "lab"}
        text = ("Does NOT make brain-wide changes, which is lab-a. Nor a brain-dump, that is `lab-b`, "
                "`brain-sync` or lab-c and lab-d, nor lab-e. Also lab-f, which is template-x.")
        self.assertEqual(skills.introduced_skills(text, prefixes),
                         ["lab-a", "lab-b", "brain-sync", "lab-c", "lab-d", "lab-e"])

    def test_introduced_skills_needs_the_exact_introducer_and_a_prefixed_name(self):
        prefixes = {"brain", "lab"}
        for text in ("this is lab-a", "Which is lab-a", "which isn't lab-a", "which is brain-wide-ish.md",
                     "which is the lab-a skill", "that is docs/lab-a", "which is", ""):
            with self.subTest(text):
                self.assertEqual(skills.introduced_skills(text, prefixes), [])
        self.assertEqual(skills.introduced_skills("which is brain-wide", prefixes), ["brain-wide"])  # shape only
        self.assertEqual(skills.introduced_skills("which is lab-a", set()), [])

    def test_owned_skills(self):
        def skill(name):
            return skills.Skill(name, Path(name), Path(name) / "SKILL.md", {}, "")

        everything = [skill("brain-sync"), skill("lab-a"), skill("template-new"), skill("other-x")]
        self.assertEqual([s.name for s in skills.owned_skills(self.cfg(), everything)],
                         ["lab-a", "template-new", "other-x"])
        self.assertEqual([s.name for s in skills.owned_skills(self.cfg(role="template"), everything)],
                         [s.name for s in everything])


if __name__ == "__main__":
    unittest.main()
