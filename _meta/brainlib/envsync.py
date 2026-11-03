"""`brain env-sync`: keep the key names in `.env` in step with `.env.example`, and never print a value.

`.env.example` is tracked and holds secret NAMES only; `.env` is ignored and holds the values. Nothing here
prints, copies or keeps a value: the only things read out of `.env` are which names it assigns and whether
each is empty, and no message quotes a line of either file. Appended lines are always `KEY=`.

    env-sync              add each name in `.env.example` that `.env` lacks, as `KEY=` (creates `.env`, mode 600)
    env-sync --add KEY    append `KEY=` to `.env.example` and to `.env`, where either lacks it
    env-sync --list       print `KEY  set|empty|missing` for each name in `.env.example`

`--add` exists because the `.env.*` read deny keeps the agent from editing `.env.example` itself.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import paths

KEY_RE = r"^[A-Za-z_][A-Za-z0-9_]*$"
_KEY = re.compile(KEY_RE)  # always used with fullmatch: `$` alone would let a trailing newline through
ENV = ".env"
EXAMPLE = ".env.example"


# -- reading --------------------------------------------------------------------------------------


def _read(path: Path) -> Optional[bytes]:
    """The file's bytes, None when it is not there. Any other failure is an OSError for the caller."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _entries(data: Optional[bytes]) -> List[Tuple[str, str]]:
    """(name, text after the `=`) for each assignment line, in file order.

    Blank lines, comments and anything that is not `NAME=...`, `export NAME=...` or a bare `NAME` are skipped.
    The text after the `=` is only ever handed to `_is_empty`.
    """
    if data is None:
        return []
    found: List[Tuple[str, str]] = []
    for line in data.decode("utf-8-sig", errors="replace").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export") and line[6:7] in (" ", "\t"):
            line = line[6:].lstrip()
        name, _equals, rest = line.partition("=")
        name = name.strip()
        if _KEY.fullmatch(name):
            found.append((name, rest))
    return found


def _is_empty(rest: str) -> bool:
    """Whether the text after a `=` assigns nothing: blank, only a comment, or an empty quoted string."""
    rest = rest.strip()
    if rest[:1] in ("'", '"'):
        close = rest.find(rest[0], 1)
        return not (rest[1:close] if close > 0 else rest[1:]).strip()
    return not re.split(r"(?:^|\s)#", rest, maxsplit=1)[0].strip()


def example_names(root: Path) -> List[str]:
    """The names `.env.example` lists, once each, in file order."""
    names: List[str] = []
    for name, _rest in _entries(_read(Path(root) / EXAMPLE)):
        if name not in names:
            names.append(name)
    return names


def env_state(root: Path) -> Dict[str, bool]:
    """name -> whether `.env` assigns it nothing. The last assignment of a name wins, as in a dotenv loader."""
    return {name: _is_empty(rest) for name, rest in _entries(_read(Path(root) / ENV))}


def statuses(root: Path) -> List[Tuple[str, str]]:
    """(name, "set" | "empty" | "missing") for each name in `.env.example`."""
    state = env_state(root)
    return [(name, "missing" if name not in state else "empty" if state[name] else "set")
            for name in example_names(root)]


# -- writing --------------------------------------------------------------------------------------


def _append(path: Path, names: List[str], private: bool) -> None:
    """Append `NAME=` lines to `path`, creating it (mode 600 when `private`). An existing file keeps its mode,
    its line endings, and whatever it holds; a missing final newline is supplied first."""
    existing = _read(path)
    newline = b"\r\n" if existing and b"\r\n" in existing else b"\n"
    chunk = b"".join(name.encode("ascii") + b"=" + newline for name in names)
    if existing and not existing.endswith(b"\n"):
        chunk = newline + chunk
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600 if private else 0o666)
    with os.fdopen(fd, "ab") as handle:
        handle.write(chunk)


def sync(root: Path) -> List[str]:
    """Add each name `.env.example` lists and `.env` lacks to `.env` as `NAME=`; return the names added."""
    root = Path(root)
    have = env_state(root)
    missing = [name for name in example_names(root) if name not in have]
    if missing:
        _append(root / ENV, missing, private=True)
    return missing


def add(root: Path, name: str) -> List[str]:
    """Append `NAME=` to `.env.example` and to `.env`, where either lacks it; return the files written."""
    root = Path(root)
    if not _KEY.fullmatch(name):
        raise ValueError("not a key name")
    written: List[str] = []
    if name not in example_names(root):
        _append(root / EXAMPLE, [name], private=False)
        written.append(EXAMPLE)
    if name not in env_state(root):
        _append(root / ENV, [name], private=True)
        written.append(ENV)
    return written


# -- the command ----------------------------------------------------------------------------------


def _key(text: str) -> str:
    if not _KEY.fullmatch(text):
        # The text is not repeated: someone may have typed NAME=value, and no value is ever printed.
        raise argparse.ArgumentTypeError(
            "a key is a name such as API_BASE_URL (letters, digits and '_', not starting with a digit); "
            "give the name alone, never a value")
    return text


def add_arguments(parser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--add", metavar="KEY", type=_key,
                      help="append KEY= to .env.example and .env where either lacks it")
    mode.add_argument("--list", action="store_true",
                      help="print each name in .env.example as 'KEY  set|empty|missing' (never a value)")


def run(args) -> int:
    root = paths.harness_root()
    try:
        if args.list:
            rows = statuses(root)
            if not rows:
                print("env-sync: .env.example lists no keys", file=sys.stderr)
            for name, status in rows:
                print(f"{name}  {status}")
            return 0
        if args.add:
            written = add(root, args.add)
            for rel in written:
                print(f"added {args.add} to {rel}")
            if not written:
                print(f"{args.add} is already in {EXAMPLE} and {ENV}")
            return 0
        if not example_names(root):
            print(f"env-sync: {EXAMPLE} lists no keys, so there is nothing to add")
            return 0
        created = not (root / ENV).exists()
        added = sync(root)
    except OSError as why:
        which = Path(str(why.filename)).name if why.filename else "the env files"
        print(f"env-sync: cannot read or write {which} ({why.strerror or why.__class__.__name__})", file=sys.stderr)
        return 1
    if added and created:
        print(f"created {ENV} (mode 600)")
    for name in added:
        print(f"added {name} to {ENV}")
    if not added:
        print(f"{ENV} already has every key in {EXAMPLE}")
    return 0
