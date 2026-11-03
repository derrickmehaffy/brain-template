from __future__ import annotations

import unittest

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import changelog, upstream

UPSTREAM = """# Upstream suggestions

Intro text that names the shape: `## <YYYY-MM-DD-slug>`.

## 2026-11-02-gate-misses-bash
- template: 0.1.0+abc1234
- files: _meta/brainlib/gate.py, .claude/skills/brain-sync/SKILL.md
- status: open
### What happened
The gate let a write through.
### Proposed change
Fence it like this:

```markdown
## 2026-11-02-not-a-heading
- status: landed 9.9.9
```

## 2026-11-03-second
- template: 0.1.0
- files: `_meta/brain`
- status: landed 0.2.0
### What happened
Something else.

## 2026-11-04-third
- template: 0.1.0
- files: docs/x with space.md, _meta/ROUTING-META.md
- status: declined: only fits one brain
### What happened
Third.

## 2026-11-05-no-status
- template: 0.1.0
- files: _meta/brain
### What happened
Written by hand, with no status line.
"""

CHANGELOG = """# Changelog

## 0.10.0 — 2026-12-01

- landed: 2026-11-02-gate-misses-bash — the gate now fences Bash writes
- declined: 2026-11-04-third — fits only one brain

## 0.9.0 — 2026-11-20

- declined: 2026-11-02-gate-misses-bash — not yet
- landed: 2026-11-03-second — fixed `_meta/brain`

## 0.2.0 — 2026-11-10

Not an answer line.

## 0.1.0 — 2026-11-02

- First version.
"""


class ParseTest(unittest.TestCase):
    def test_parse_status(self):
        found = upstream.parse(UPSTREAM)
        self.assertEqual([s.id for s in found], [
            "2026-11-02-gate-misses-bash", "2026-11-03-second", "2026-11-04-third", "2026-11-05-no-status"])
        self.assertEqual([s.status for s in found], ["open", "landed 0.2.0", "declined: only fits one brain", "open"])
        self.assertEqual([s.state for s in found], ["open", "landed", "declined", "open"])
        self.assertEqual(found[0].files, ["_meta/brainlib/gate.py", ".claude/skills/brain-sync/SKILL.md"])
        self.assertEqual(found[1].files, ["_meta/brain"])  # backticks around a path are not part of it
        self.assertEqual(found[2].files, ["docs/x with space.md", "_meta/ROUTING-META.md"])
        self.assertIn("The gate let a write through.", found[0].body)
        self.assertIn("### Proposed change", found[0].body)

    def test_a_heading_inside_a_code_fence_does_not_start_an_entry(self):
        found = upstream.parse(UPSTREAM)
        self.assertNotIn("2026-11-02-not-a-heading", [s.id for s in found])
        self.assertIn("## 2026-11-02-not-a-heading", found[0].body)
        self.assertEqual(found[0].status, "open")  # the fenced `- status:` line is not the entry's

    def test_open_ids(self):
        self.assertEqual(upstream.open_ids(UPSTREAM), ["2026-11-02-gate-misses-bash", "2026-11-05-no-status"])

    def test_empty_and_preamble_only_text(self):
        self.assertEqual(upstream.parse(""), [])
        self.assertEqual(upstream.open_ids("# Upstream suggestions\n\nNothing yet.\n"), [])

    def test_status_text_is_kept_whole(self):
        text = "## 2026-01-01-x\n- status:   declined:  a reason: with a colon  \n"
        (only,) = upstream.parse(text)
        self.assertEqual(only.status, "declined:  a reason: with a colon")
        self.assertEqual(only.state, "declined")

    def test_crlf_text_parses(self):
        found = upstream.parse(UPSTREAM.replace("\n", "\r\n"))
        self.assertEqual([s.status for s in found][:3], ["open", "landed 0.2.0", "declined: only fits one brain"])
        self.assertEqual(found[0].files[0], "_meta/brainlib/gate.py")


class ChangelogTest(unittest.TestCase):
    def test_entries(self):
        found = changelog.entries(CHANGELOG)
        self.assertEqual([version for version, _ in found], ["0.10.0", "0.9.0", "0.2.0", "0.1.0"])
        self.assertIn("- landed: 2026-11-02-gate-misses-bash", found[0][1])
        self.assertNotIn("0.9.0", found[0][1])
        self.assertEqual(found[3][1], "- First version.")

    def test_changelog_semver_order(self):
        newer = [version for version, _ in changelog.newer_than(CHANGELOG, "0.9.0")]
        self.assertEqual(newer, ["0.10.0"])  # 0.10.0 is newer than 0.9.0, not older as a string compare says
        self.assertEqual([v for v, _ in changelog.newer_than(CHANGELOG, "0.1.0")], ["0.10.0", "0.9.0", "0.2.0"])
        self.assertEqual(changelog.newer_than(CHANGELOG, "0.10.0"), [])
        self.assertEqual(changelog.newer_than(CHANGELOG, "1.0.0"), [])

    def test_the_sha_suffix_is_ignored(self):
        self.assertEqual([v for v, _ in changelog.newer_than(CHANGELOG, "0.9.0+abcdef1")], ["0.10.0"])
        self.assertEqual(changelog.newer_than(CHANGELOG, "0.10.0+abcdef1"), [])

    def test_an_unknown_version_gets_every_entry(self):
        everything = ["0.10.0", "0.9.0", "0.2.0", "0.1.0"]
        for unknown in ("", "not a version", None):
            with self.subTest(unknown=unknown):
                self.assertEqual([v for v, _ in changelog.newer_than(CHANGELOG, unknown)], everything)

    def test_answers(self):
        found = changelog.answers(changelog.entries(CHANGELOG))
        self.assertEqual(found, {
            "2026-11-02-gate-misses-bash": ("landed", "0.10.0"),  # the newest answer wins over 0.9.0's
            "2026-11-03-second": ("landed", "0.9.0"),
            "2026-11-04-third": ("declined", "fits only one brain"),
        })

    def test_answers_of_the_newer_entries_only(self):
        found = changelog.answers(changelog.newer_than(CHANGELOG, "0.9.0"))
        self.assertEqual(sorted(found), ["2026-11-02-gate-misses-bash", "2026-11-04-third"])

    def test_answer_line_shapes(self):
        text = ("## 1.0.0 — 2026-01-01\n\n"
                "- landed: 2026-01-01-a — fixed — twice\n"
                "- declined: 2026-01-01-b—no space around the dash\n"
                "* landed: 2026-01-01-c - plain hyphen\n"
                "- declined: 2026-01-01-d\n"
                "- landing: 2026-01-01-e — not a keyword\n"
                "  - landed: 2026-01-01-f — indented answers count\n")
        found = changelog.answers(changelog.entries(text))
        self.assertEqual(found["2026-01-01-a"], ("landed", "1.0.0"))
        self.assertEqual(found["2026-01-01-b"], ("declined", "no space around the dash"))
        self.assertEqual(found["2026-01-01-c"], ("landed", "1.0.0"))
        self.assertEqual(found["2026-01-01-d"], ("declined", ""))
        self.assertNotIn("2026-01-01-e", found)
        self.assertEqual(found["2026-01-01-f"], ("landed", "1.0.0"))

    def test_text_without_entries(self):
        self.assertEqual(changelog.entries(""), [])
        self.assertEqual(changelog.entries("# Changelog\n\nnothing yet\n"), [])
        self.assertEqual(changelog.answers([]), {})

    def test_a_heading_inside_a_code_fence_is_not_an_entry(self):
        text = "## 0.2.0 — 2026-01-02\n\n```\n## 0.3.0 — fake\n```\n\n## 0.1.0 — 2026-01-01\n- x\n"
        self.assertEqual([v for v, _ in changelog.entries(text)], ["0.2.0", "0.1.0"])


class ListTest(TempDirCase):
    def brain_with(self, text, changelog_text=None, label="brain"):
        root = self.fake_brain()
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / "UPSTREAM.md").write_text(text, encoding="utf-8")
        if changelog_text is not None:
            (root / "_meta" / "CHANGELOG.md").write_text(changelog_text, encoding="utf-8")
        return root

    def lines(self, result):
        return [line for line in result.stdout.splitlines() if line.strip()]

    def test_list_in_brain(self):
        root = self.brain_with(UPSTREAM)
        r = self.run_brain(root, "upstream", "list")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.lines(r), [
            f"{root}  2026-11-02-gate-misses-bash  open",
            f"{root}  2026-11-03-second  landed 0.2.0",
            f"{root}  2026-11-04-third  declined: only fits one brain",
            f"{root}  2026-11-05-no-status  open",
        ])

    def test_list_shows_the_templates_answer(self):
        root = self.brain_with(UPSTREAM, CHANGELOG)
        r = self.run_brain(root, "upstream", "list")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.lines(r), [
            f"{root}  2026-11-02-gate-misses-bash  open  answer: landed 0.10.0",
            f"{root}  2026-11-03-second  landed 0.2.0  answer: landed 0.9.0",
            f"{root}  2026-11-04-third  declined: only fits one brain  answer: declined: fits only one brain",
            f"{root}  2026-11-05-no-status  open",
        ])

    def test_list_in_a_brain_without_upstream_md(self):
        root = self.fake_brain()
        r = self.run_brain(root, "upstream", "list")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no upstream suggestions", r.stdout)

    def test_list_in_template_reads_registry(self):
        template = self.copy_template()
        first = self.brain_with(UPSTREAM)
        second = self.brain_with("## 2026-12-01-other\n- template: 0.1.0\n- files: _meta/brain\n- status: open\n")
        gone = self.tmp / "no such brain"
        listing = (f"# the brains\n\n{first}\n{gone}\n   \n{second}  \n")
        (template / "local" / "brains.txt").write_text(listing, encoding="utf-8")
        (template / "_meta" / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        r = self.run_brain(template, "upstream", "list")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        listed = [line for line in self.lines(r) if line.startswith(("/", str(self.tmp)))]
        self.assertEqual(listed[0], f"{first}  2026-11-02-gate-misses-bash  open  answer: landed 0.10.0")
        self.assertEqual(len([line for line in listed if line.startswith(str(first))]), 4)
        self.assertEqual(listed[-1], f"{second}  2026-12-01-other  open")
        self.assertIn(f"WARN   upstream: {gone}: not a folder", r.stdout)

    def test_list_in_template_with_a_path_reads_only_that_brain(self):
        template = self.copy_template()
        listed = self.brain_with("## 2026-12-01-listed\n- status: open\n")
        elsewhere = self.brain_with("## 2026-12-02-elsewhere\n- status: open\n")
        (template / "local" / "brains.txt").write_text(f"{listed}\n", encoding="utf-8")
        r = self.run_brain(template, "upstream", "list", str(elsewhere))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.lines(r), [f"{elsewhere}  2026-12-02-elsewhere  open"])

    def test_list_in_template_without_a_registry(self):
        template = self.copy_template(with_local=False)
        r = self.run_brain(template, "upstream", "list")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no brains listed", r.stdout)

    def test_list_with_a_bad_path_is_a_refusal(self):
        root = self.brain_with(UPSTREAM)
        r = self.run_brain(root, "upstream", "list", str(self.tmp / "missing"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not a folder", r.stderr)

    def test_list_needs_a_subcommand(self):
        r = self.run_brain(self.fake_brain(), "upstream")
        self.assertEqual(r.returncode, 2)

    def test_list_never_writes(self):
        template = self.copy_template()
        brain = self.brain_with(UPSTREAM, CHANGELOG)
        (template / "local" / "brains.txt").write_text(f"{brain}\n", encoding="utf-8")
        before = (self.snapshot(template), self.snapshot(brain))
        self.assertEqual(self.run_brain(template, "upstream", "list").returncode, 0)
        self.assertEqual(self.run_brain(brain, "upstream", "list").returncode, 0)
        self.assertEqual((self.snapshot(template), self.snapshot(brain)), before)


if __name__ == "__main__":
    unittest.main()
