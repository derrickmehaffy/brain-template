"""The template's `_meta/CHANGELOG.md`: its entries, which of them are newer than a version, and which upstream
suggestions they answer (spec §6).

An entry is a heading `## <semver> — <YYYY-MM-DD>` and the lines under it. A line `- landed: <id> — <summary>`
or `- declined: <id> — <reason>` answers the suggestion with that id. `template-intake` writes them and
`upstream list` and `update` read them.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

Entry = Tuple[str, str]  # (version, body)

CHANGELOG_PATH = "_meta/CHANGELOG.md"

_HEADING = re.compile(r"^##[ \t]+v?(\d+(?:\.\d+)*)(?=[\s+]|$)")
# `- landed: <id> — <summary>`. The id runs up to white space or a dash (so `<id>— text` works too); the dash is
# an em or en dash, `--`, or a plain hyphen set apart by white space. Indented lines and `*` or `+` bullets count.
_ANSWER = re.compile(
    r"^[ \t]*[-*+][ \t]+(landed|declined)[ \t]*:[ \t]*(\S+?)(?=[\s—–]|$)[ \t]*(?:[—–]|--|-(?=\s))?[ \t]*(.*?)[ \t]*$",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def fence_mask(lines: List[str]) -> List[bool]:
    """For each line, whether it is a code fence or inside one. A heading or a list line shown inside a fence is an
    example, not structure."""
    mask: List[bool] = []
    opened: Optional[str] = None  # the fence that is open: its marker run
    for line in lines:
        found = _FENCE.match(line.rstrip("\r"))
        if opened is not None:
            mask.append(True)
            if found and found.group(1)[0] == opened[0] and len(found.group(1)) >= len(opened) \
                    and not found.group(2).strip():
                opened = None
        elif found and not (found.group(1)[0] == "`" and "`" in found.group(2)):
            mask.append(True)
            opened = found.group(1)
        else:
            mask.append(False)
    return mask


def version_key(version: Optional[str]) -> Tuple[int, ...]:
    """`version` as a tuple of integers, so `0.10.0` sorts after `0.9.0`. A `+sha` suffix (as in
    `brain.json` `template.version`) and a leading `v` are ignored; anything that is not a version gives `()`."""
    if not version:
        return ()
    core = version.strip().split("+", 1)[0].lstrip("vV")
    parts = core.split(".")
    if not all(part.isdigit() for part in parts):
        return ()
    return tuple(int(part) for part in parts)


def entries(text: str) -> List[Entry]:
    """The entries of `text` in document order (newest first, by convention) as (version, body); the body is the
    text under the heading, without blank lines at either end. A heading inside a code fence starts nothing."""
    lines = text.split("\n")
    mask = fence_mask(lines)
    found: List[Entry] = []
    version: Optional[str] = None
    body: List[str] = []

    def close() -> None:
        if version is not None:
            found.append((version, "\n".join(line.rstrip("\r") for line in body).strip("\n")))

    for line, fenced in zip(lines, mask):
        heading = None if fenced else _HEADING.match(line.rstrip("\r"))
        if heading:
            close()
            version, body = heading.group(1), []
        elif version is not None:
            body.append(line)
    close()
    return found


def newer_than(text: str, version: Optional[str]) -> List[Entry]:
    """The entries of `text` whose version is greater than `version` (compared as integers; `+sha` ignored), in
    document order. A `version` that is empty or unreadable gives every entry: nothing is known to be taken in."""
    floor = version_key(version)
    return [(v, body) for v, body in entries(text) if not floor or version_key(v) > floor]


def answers(found: List[Entry]) -> Dict[str, Tuple[str, str]]:
    """id -> ("landed", version) or ("declined", reason) for every answer line in `found`. An id answered more
    than once keeps its newest answer (the entry with the greatest version)."""
    result: Dict[str, Tuple[str, str]] = {}
    for version, body in sorted(found, key=lambda entry: version_key(entry[0])):
        lines = body.split("\n")
        for line, fenced in zip(lines, fence_mask(lines)):
            match = None if fenced else _ANSWER.match(line)
            if not match:
                continue
            kind, suggestion, rest = match.group(1).lower(), match.group(2), match.group(3)
            result[suggestion] = ("landed", version) if kind == "landed" else ("declined", rest)
    return result
