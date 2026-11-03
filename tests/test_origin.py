"""Origin check: no file of the template names the organisations, products, systems or people its source
brains came from, and none holds an absolute home path.

The term list lives in `local/origin-terms.txt`, which is ignored, so this test (and the repository) never
carries the terms themselves. Only the main checkout has that file; anywhere else the term scan skips with a
notice. A finding names the file, the line and the number of the term, never the term.

`git ls-files` is the set of files scanned, plus files not yet added that git does not ignore, so a new file
is checked before it is staged.
"""
from __future__ import annotations

import os
import pwd
import re
import unittest
from typing import Iterator, List, Tuple

from tests.helpers import TEMPLATE_ROOT, TempDirCase  # first: puts <template>/_meta on sys.path

TERMS_FILE = TEMPLATE_ROOT / "local" / "origin-terms.txt"


def read_terms(text: str) -> List[str]:
    """The terms in a term list: one per line, blank lines and `#` comments left out."""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def term_pattern(term: str) -> "re.Pattern[str]":
    """A whole word (no letter, digit or underscore either side), whatever the case."""
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])", re.IGNORECASE)


def find_terms(text: str, terms: List[str]) -> List[Tuple[int, int]]:
    """(line number, term number) for each line of `text` holding a term, numbers counted from 1."""
    patterns = [term_pattern(term) for term in terms]
    found = []
    for number, line in enumerate(text.split("\n"), start=1):
        for index, pattern in enumerate(patterns, start=1):
            if pattern.search(line):
                found.append((number, index))
    return found


class OriginCase(TempDirCase):
    def tracked(self) -> Iterator[Tuple[str, str]]:
        """(relative path, text) of each file git tracks or would track, undecodable bytes replaced."""
        listed = self.git(TEMPLATE_ROOT, "ls-files", "-co", "--exclude-standard", "-z")
        for rel in sorted(set(p for p in listed.split("\0") if p)):
            full = TEMPLATE_ROOT / rel
            if not full.is_file():  # tracked, deleted in the working tree
                continue
            yield rel, full.read_bytes().decode("utf-8", errors="replace")

    def test_matcher_is_whole_word_and_case_insensitive(self):
        terms = ["acme-widget", "Zed"]
        self.assertEqual(find_terms("a\nthe ACME-Widget team\nzed.", terms), [(2, 1), (3, 2)])
        self.assertEqual(find_terms("acme-widgets, xzed, zed2, _zed", terms), [])
        self.assertEqual(find_terms("(acme-widget)", terms), [(1, 1)])
        self.assertEqual(read_terms("# a comment\n\n  Foo  \nbar\n"), ["Foo", "bar"])

    def test_no_origin_terms_in_tracked_files(self):
        if not TERMS_FILE.is_file():
            self.skipTest("local/origin-terms.txt is absent (it exists only in the main checkout): "
                          "the origin-term scan was skipped")
        terms = read_terms(TERMS_FILE.read_text(encoding="utf-8", errors="replace"))
        self.assertTrue(terms, "local/origin-terms.txt lists no terms")
        problems = []
        scanned = 0
        for rel, text in self.tracked():
            scanned += 1
            problems += [f"{rel}: its name holds term {n}" for _line, n in find_terms(rel, terms)]
            problems += [f"{rel}:{line}: term {n}" for line, n in find_terms(text, terms)]
        self.assertGreater(scanned, 0, "git listed no files")
        self.assertEqual(problems, [], "files that name a source brain's organisation, product, system or person "
                                       "(term numbers count lines of local/origin-terms.txt that hold a term)")

    def test_no_home_paths(self):
        # The real home from the password database: tests redirect HOME, so Path.home() could be a temp folder.
        home = pwd.getpwuid(os.getuid()).pw_dir.rstrip("/")
        if len(home) < 4:
            self.skipTest("the home folder is too short to tell a home path from any other path")
        pattern = re.compile(re.escape(home) + r"(?![A-Za-z0-9_])")
        problems = []
        for rel, text in self.tracked():
            if pattern.search(rel):
                problems.append(f"{rel}: its name holds the home path")
            for number, line in enumerate(text.split("\n"), start=1):
                if pattern.search(line):
                    problems.append(f"{rel}:{number}: holds the home path")
        self.assertEqual(problems, [], "absolute home paths in files that ship or document the template; "
                                       "write an illustrative path such as /home/me instead")


if __name__ == "__main__":
    unittest.main()
