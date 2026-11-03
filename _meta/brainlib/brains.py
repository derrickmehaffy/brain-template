"""`brain brains list|add|handoff`: the other brains this one knows, for a brain that routes work to them (a hub).

`brain.json` `brains` lists their folders, relative to this brain or starting with `~`, so the list reads the same on
every machine with the same layout. `list` reads each one's `brain.json` and open inbox; `add` checks a folder is a
brain before listing it; `handoff` appends an open entry to that brain's `docs/INBOX.md`, the only file it writes in
another brain, and never commits there: the receiving brain works the entry and commits it. Another brain is read,
never edited otherwise.
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import config, inbox, paths

KEY = "brains"


def add_arguments(parser) -> None:
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("list", help="each known brain: name, folder, what it is for, open hand-offs (the default)")
    add = sub.add_parser("add", help="check a folder is a brain and add it to brain.json brains")
    add.add_argument("folder", help="the brain's folder: relative to this brain, absolute, or starting with ~")
    send = sub.add_parser("handoff", help="append an open entry to a known brain's docs/INBOX.md; never commits there")
    send.add_argument("brain", help="the brain's name (from its brain.json) or its folder as listed")
    send.add_argument("--title", required=True, help="one line: what is being handed over")
    body = send.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="the request, in full: what to do, why, and anything already found")
    body.add_argument("--body-file", metavar="FILE", help="read the request from FILE ('-' for standard input)")


def _resolve(root: Path, folder: str) -> Path:
    return (root / os.path.expanduser(folder)).resolve()


def _listed(cfg: config.Config) -> List[str]:
    value = cfg.raw.get(KEY, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise config.ConfigError(f"brain.json {KEY} must be a list of folder names")
    return value


def _brain_at(folder: Path) -> Tuple[Optional[config.Config], str]:
    """(its config, "") for a brain, else (None, why not)."""
    if not (folder / "brain.json").is_file():
        return None, "no brain.json there"
    try:
        other = config.load(folder)
    except config.ConfigError as exc:
        return None, f"its brain.json does not load: {exc}"
    if other.role != "brain":
        return None, f"its brain.json role is {other.role!r}, not a brain"
    return other, ""


def _list(root: Path, cfg: config.Config) -> int:
    listed = _listed(cfg)
    if not listed:
        print(f"brains: none listed; add one with `_meta/brain brains add <folder>` (brain.json {KEY})")
        return 0
    for folder in listed:
        other, why = _brain_at(_resolve(root, folder))
        if other is None:
            print(f"{folder}  MISSING: {why}")
            continue
        waiting = len(inbox.open_entries(_resolve(root, folder)))
        tail = f"  [{waiting} open hand-off{'s' if waiting != 1 else ''}]" if waiting else ""
        print(f"{other.raw.get('name', '?')}  {folder}  {other.prefix}-*  {other.raw.get('description', '')}{tail}")
    return 0


def _add(root: Path, cfg: config.Config, folder: str) -> int:
    target = _resolve(root, folder)
    if target == root.resolve():
        return _refuse("that is this brain")
    other, why = _brain_at(target)
    if other is None:
        return _refuse(f"{folder} is not a brain: {why}")
    listed = _listed(cfg)
    if any(_resolve(root, item) == target for item in listed):
        print(f"brains: {folder} is already listed")
        return 0
    raw = dict(cfg.raw)
    raw[KEY] = listed + [folder]
    config.write_raw(root, raw)
    print(f"brains: added {other.raw.get('name', folder)} ({folder}) to brain.json {KEY}; commit it through brain-sync")
    return 0


def _find(root: Path, cfg: config.Config, wanted: str) -> Optional[Path]:
    for folder in _listed(cfg):
        target = _resolve(root, folder)
        other, _why = _brain_at(target)
        if other is not None and wanted in (other.raw.get("name"), folder):
            return target
    return None


def _handoff(root: Path, cfg: config.Config, args) -> int:
    title = " ".join(args.title.split())
    if not title:
        return _refuse("--title is empty")
    if args.body_file:
        try:
            body = sys.stdin.read() if args.body_file == "-" else Path(args.body_file).read_text(encoding="utf-8")
        except OSError as exc:
            return _refuse(f"cannot read {args.body_file}: {exc.strerror or exc}")
    else:
        body = args.body or ""
    if not body.strip():
        return _refuse("the request is empty: say what to do, why, and anything already found")
    target = _find(root, cfg, args.brain)
    if target is None:
        return _refuse(f"{args.brain!r} is not a listed brain; `_meta/brain brains list` shows them")
    path = target / inbox.INBOX
    for step in (target / "docs", path):
        if step.is_symlink():
            return _refuse(f"{step} is a link; a hand-off is written only to a real file in that brain")
    if not path.exists():
        header = root / inbox.HEADER
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header.read_text(encoding="utf-8") if header.is_file() else "# Inbox\n", encoding="utf-8")
    source = str(cfg.raw.get("name") or root.name)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(inbox.entry_text(source, title, body, datetime.date.today()))
    print(f"brains: handed over to {target}: {inbox.INBOX.as_posix()} now has an open entry {title!r}. Nothing was "
          "committed there; the next chat in that brain is told about it.")
    return 0


def _refuse(message: str) -> int:
    print(f"brains: {message}", file=sys.stderr)
    return 1


def run(args) -> int:
    root = paths.harness_root()
    try:
        cfg = config.load(root)
        if args.action == "add":
            return _add(root, cfg, args.folder)
        if args.action == "handoff":
            return _handoff(root, cfg, args)
        return _list(root, cfg)
    except config.ConfigError as exc:
        return _refuse(str(exc))
