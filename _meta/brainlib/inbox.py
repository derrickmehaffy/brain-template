"""`docs/INBOX.md`: work another brain handed over to this one.

Each entry is a `## <date> · from <brain> · <title>` heading followed by `- status: open|done|declined: <reason>`
and the request. `brains handoff` appends entries from the brain that hands the work over; the receiving brain sets
the status when the work is done, and `doctor` reports the entries still open.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import List, NamedTuple

INBOX = Path("docs") / "INBOX.md"
HEADER = Path("_meta") / "skeleton" / "docs" / "INBOX.md"  # the file a new inbox starts from

_STATUS = re.compile(r"^[ \t]*[-*+][ \t]+status[ \t]*:[ \t]*(.*?)[ \t]*$", re.IGNORECASE)


class Entry(NamedTuple):
    heading: str  # the text after `## `
    status: str  # the text after `- status:`; "open" when absent

    @property
    def is_open(self) -> bool:
        return self.status.split(":")[0].strip().lower() in ("", "open")


def parse(text: str) -> List[Entry]:
    entries: List[Entry] = []
    heading, status = None, ""
    for line in text.splitlines():
        if line.startswith("## "):
            if heading is not None:
                entries.append(Entry(heading, status or "open"))
            heading, status = line[3:].strip(), ""
        elif heading is not None and not status:
            match = _STATUS.match(line)
            if match:
                status = match.group(1)
    if heading is not None:
        entries.append(Entry(heading, status or "open"))
    return entries


def open_entries(root: Path) -> List[Entry]:
    try:
        text = (root / INBOX).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [entry for entry in parse(text) if entry.is_open]


def entry_text(source: str, title: str, body: str, day: datetime.date) -> str:
    """One entry, ready to append: the heading, an open status and the request."""
    return f"\n## {day.isoformat()} · from {source} · {title}\n- status: open\n\n{body.strip()}\n"
