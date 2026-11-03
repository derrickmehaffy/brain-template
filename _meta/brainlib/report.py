"""Findings and the one line format every checking command prints."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Iterable, Optional, TextIO, Tuple

OK = "ok"
WARN = "WARN"
BLOCK = "BLOCK"
BROKEN = "BROKEN"
GAP = "GAP"
ORPHAN = "ORPHAN"


@dataclass(frozen=True)
class Finding:
    severity: str
    subject: str
    message: str


def emit(findings: Iterable[Finding], out: Optional[TextIO] = None) -> None:
    """Print one `<severity> <subject>: <message>` line per finding (stdout by default)."""
    out = sys.stdout if out is None else out
    for f in findings:
        print(f"{f.severity:<6} {f.subject}: {f.message}", file=out)


def exit_code(findings: Iterable[Finding], failing: Tuple[str, ...] = (BLOCK, BROKEN)) -> int:
    """1 when any finding has a failing severity, else 0."""
    return 1 if any(f.severity in failing for f in findings) else 0
