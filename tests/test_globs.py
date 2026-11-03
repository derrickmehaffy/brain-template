from __future__ import annotations

import unittest

import tests.helpers  # noqa: F401  first: puts <template>/_meta on sys.path
from brainlib import globs


class GlobMatchTest(unittest.TestCase):
    def assert_matches(self, pattern, relpath):
        self.assertTrue(globs.match(pattern, relpath), f"{pattern!r} should match {relpath!r}")

    def assert_misses(self, pattern, relpath):
        self.assertFalse(globs.match(pattern, relpath), f"{pattern!r} should not match {relpath!r}")

    def test_star_does_not_cross_slash(self):
        self.assertFalse(globs.match("scripts/*", "scripts/a/b.py"))
        self.assert_matches("scripts/*", "scripts/a.py")
        self.assert_matches("out/*.md", "out/a.md")
        self.assert_misses("out/*.md", "out/sub/a.md")
        self.assert_misses("out/*.md", "out/a.txt")

    def test_question_mark_is_one_character_and_never_a_slash(self):
        self.assert_matches("docs/?.md", "docs/a.md")
        self.assert_misses("docs/?.md", "docs/ab.md")
        self.assert_misses("docs/?.md", "docs//.md")
        self.assert_misses("a?b", "a/b")

    def test_double_star(self):
        self.assert_matches("scripts/**", "scripts/a.py")
        self.assert_matches("scripts/**", "scripts/a/b.py")
        self.assert_matches("scripts/**", "scripts/a/b/c/d.py")
        self.assert_misses("scripts/**", "scripts")
        self.assert_misses("scripts/**", "other/scripts/a.py")

    def test_double_star_below_a_folder_matches_everything_in_it(self):
        for relpath in ("docs/practices/a.md", "docs/practices/x/y/z.md", "docs/practices/.hidden"):
            self.assert_matches("docs/practices/**", relpath)
        self.assert_misses("docs/practices/**", "docs/practices.md")
        self.assert_misses("docs/practices/**", "docs/other/a.md")

    def test_double_star_between_folders_matches_zero_or_more(self):
        self.assert_matches("a/**/b", "a/b")
        self.assert_matches("a/**/b", "a/x/b")
        self.assert_matches("a/**/b", "a/x/y/b")
        self.assert_misses("a/**/b", "a/xb")
        self.assert_matches("**/SKILL.md", "SKILL.md")
        self.assert_matches("**/SKILL.md", "a/b/SKILL.md")
        self.assert_misses("**/SKILL.md", "a/b/NOTSKILL.md")

    def test_skill_prefix_glob(self):
        pattern = ".claude/skills/lab-*/**"
        self.assert_matches(pattern, ".claude/skills/lab-x/SKILL.md")
        self.assert_matches(pattern, ".claude/skills/lab-x/references/r.md")
        self.assert_misses(pattern, ".claude/skills/brain-x/SKILL.md")
        self.assert_misses(pattern, ".claude/skills/lab/SKILL.md")
        self.assert_misses(pattern, ".claude/skills/lab-x")

    def test_patterns_are_anchored(self):
        self.assert_matches("docs/ROUTING.md", "docs/ROUTING.md")
        self.assert_misses("docs/ROUTING.md", "x/docs/ROUTING.md")
        self.assert_misses("docs/ROUTING.md", "docs/ROUTING.md.bak")
        self.assert_misses("docs/ROUTING.md", "docs/ROUTING.mdx")

    def test_other_characters_are_literal(self):
        self.assert_misses("docs/a.b", "docs/aXb")
        self.assert_matches("docs/a+b", "docs/a+b")
        self.assert_misses("docs/a+b", "docs/aab")
        self.assert_matches("docs/[x]", "docs/[x]")
        self.assert_misses("docs/[x]", "docs/x")
        self.assert_matches("docs/my file.md", "docs/my file.md")
        self.assert_matches("docs/(a)", "docs/(a)")

    def test_a_leading_dot_slash_or_slash_on_the_pattern_is_ignored(self):
        self.assert_matches("./docs/ROUTING.md", "docs/ROUTING.md")
        self.assert_matches("/docs/ROUTING.md", "docs/ROUTING.md")
        self.assert_matches(".claude/**", ".claude/settings.json")

    def test_a_star_matches_a_leading_dot_and_an_empty_segment_part(self):
        self.assert_matches("docs/*", "docs/.hidden")
        self.assert_matches("a*b", "ab")
        self.assert_matches("a/*", "a/")  # a trailing slash marks a folder target; * may be empty


if __name__ == "__main__":
    unittest.main()
