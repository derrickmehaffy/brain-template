"""`brain upstream`: the suggestions a brain sends to the template, kept in its `docs/UPSTREAM.md` (spec §6).

Each suggestion is a `## <YYYY-MM-DD-slug>` heading, then `- template: <version>`, `- files: <paths>` and
`- status: open|landed <version>|declined: <reason>`, then the sections `### What happened` and
`### Proposed change`. `brain-upstream` writes them, `template-intake` answers them in the template's
`CHANGELOG.md`, and `brain-sync` flips the status when an update brings the answer in.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import changelog, config, paths
from .report import WARN, Finding, emit

UPSTREAM_PATH = "docs/UPSTREAM.md"
REGISTRY = "local/brains.txt"

_FIELD = re.compile(r"^[ \t]*[-*+][ \t]+(template|files|status)[ \t]*:[ \t]*(.*?)[ \t]*$", re.IGNORECASE)


@dataclass(frozen=True)
class Suggestion:
    id: str
    status: str  # the text after `- status:`: "open", "landed 0.2.0" or "declined: <reason>"; "open" when absent
    files: List[str]
    body: str  # everything under the heading, the three lines and both sections

    @property
    def state(self) -> str:
        """`open`, `landed` or `declined`: the first word of the status, lower case."""
        word = re.match(r"[A-Za-z]+", self.status)
        return word.group(0).lower() if word else ""


def _files(value: str) -> List[str]:
    return [item for item in (part.strip().strip("`").strip() for part in value.split(",")) if item]


def _suggestion(heading: str, lines: List[str]) -> Suggestion:
    fields: Dict[str, str] = {}
    for line in lines:
        if line.startswith("#"):  # the first section ends the three lines
            break
        found = _FIELD.match(line)
        if found:
            fields.setdefault(found.group(1).lower(), found.group(2))
    return Suggestion(heading, fields.get("status") or "open", _files(fields.get("files", "")),
                      "\n".join(lines).strip("\n"))


def parse(text: str) -> List[Suggestion]:
    """The suggestions in `text`, in file order. Text before the first heading is ignored, and a heading shown
    inside a code fence (a proposed change that quotes markdown) starts nothing."""
    lines = [line.rstrip("\r") for line in text.split("\n")]
    found: List[Suggestion] = []
    heading: Optional[str] = None
    body: List[str] = []
    for line, fenced in zip(lines, changelog.fence_mask(lines)):
        if not fenced and line.startswith("## ") and line[3:].strip():
            if heading is not None:
                found.append(_suggestion(heading, body))
            heading, body = line[3:].strip(), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        found.append(_suggestion(heading, body))
    return found


def open_ids(text: str) -> List[str]:
    """The ids of the suggestions that are still `open`."""
    return [s.id for s in parse(text) if s.state == "open"]


# -- upstream list ----------------------------------------------------------------------------------


def add_arguments(parser) -> None:
    sub = parser.add_subparsers(dest="upstream_command", metavar="<subcommand>", required=True)
    listing = sub.add_parser(
        "list", help="list upstream suggestions and the template's answers",
        description="List upstream suggestions, one line each: <brain>  <id>  <status>, plus the template's "
                    "answer when its changelog has one. With no path, a brain lists its own docs/UPSTREAM.md "
                    "and the template lists every brain in local/brains.txt.")
    listing.add_argument("brains", nargs="*", metavar="BRAIN_PATH",
                         help="the brains to read instead (a clone of a brain kept elsewhere, say)")


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _registered(root: Path) -> List[str]:
    """The brain paths listed in `local/brains.txt`, one per line as written (a path may contain spaces);
    blank lines and `#` comments are skipped."""
    text = _read(root / REGISTRY)
    if text is None:
        return []
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _answer_text(answer: Tuple[str, str]) -> str:
    kind, detail = answer
    return f"landed {detail}" if kind == "landed" else f"declined: {detail}".rstrip()


def _list(args) -> int:
    root = paths.harness_root()
    try:
        cfg = config.load(root)
    except config.ConfigError as exc:
        print(f"upstream: {exc}", file=sys.stderr)
        return 1
    if args.brains:
        targets = [os.path.abspath(path) for path in args.brains]
        for given, target in zip(args.brains, targets):
            if not os.path.isdir(target):
                print(f"upstream: {given} is not a folder", file=sys.stderr)
                return 1
    elif cfg.role == "template":
        targets = _registered(root)
        if not targets:
            print(f"no brains listed in {REGISTRY} (one absolute path per line); pass a brain's path to read it")
            return 0
    else:
        targets = [str(root)]

    text = _read(root / changelog.CHANGELOG_PATH)
    answered = changelog.answers(changelog.entries(text)) if text else {}
    lines: List[str] = []
    findings: List[Finding] = []
    for target in targets:
        if not os.path.isdir(target):
            findings.append(Finding(WARN, "upstream", f"{target}: not a folder"))
            continue
        doc = _read(Path(target) / UPSTREAM_PATH)
        if doc is None:
            findings.append(Finding(WARN, "upstream", f"{target}: no {UPSTREAM_PATH}"))
            continue
        for suggestion in parse(doc):
            line = f"{target}  {suggestion.id}  {suggestion.status}"
            if suggestion.id in answered:
                line += f"  answer: {_answer_text(answered[suggestion.id])}"
            lines.append(line)
    emit(findings)
    for line in lines:
        print(line)
    if not lines:
        print("no upstream suggestions")
    return 0


def run(args) -> int:
    if args.upstream_command == "list":
        return _list(args)
    return 2
