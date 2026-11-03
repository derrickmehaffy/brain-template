from __future__ import annotations

import io
import unittest

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import report
from brainlib.report import Finding


class ReportTest(TempDirCase):
    def test_line_format_is_pinned(self):
        out = io.StringIO()
        report.emit([Finding(report.OK, "git", "found"), Finding(report.WARN, "brain.json", "edited"),
                     Finding(report.BROKEN, "lab-a", "no name"), Finding(report.ORPHAN, "lab-b", "unused")], out)
        self.assertEqual(out.getvalue().splitlines(),
                         ["ok     git: found", "WARN   brain.json: edited",
                          "BROKEN lab-a: no name", "ORPHAN lab-b: unused"])

    def test_emit_defaults_to_current_stdout(self):
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report.emit([Finding(report.GAP, "lab-a", "no Does NOT")])
        self.assertEqual(buf.getvalue(), "GAP    lab-a: no Does NOT\n")

    def test_exit_code(self):
        f = lambda sev: [Finding(sev, "s", "m")]  # noqa: E731
        self.assertEqual(report.exit_code([]), 0)
        for sev in (report.OK, report.WARN, report.GAP, report.ORPHAN):
            self.assertEqual(report.exit_code(f(sev)), 0, sev)
        for sev in (report.BLOCK, report.BROKEN):
            self.assertEqual(report.exit_code(f(sev)), 1, sev)
        self.assertEqual(report.exit_code(f(report.GAP), failing=(report.GAP,)), 1)

    def test_finding_is_frozen(self):
        with self.assertRaises(Exception):
            Finding(report.OK, "s", "m").severity = report.BLOCK  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
