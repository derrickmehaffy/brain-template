"""`brain rename-skill OLD NEW [--apply]`: rename a skill everywhere it is named (spec §7.5).

A dry run (the default) lists the files that would change and how many times; `--apply` moves the folder
(`git mv` when git tracks it), rewrites every reference, then runs `routing sync` so the `## Where this sits`
blocks follow the new name.

A reference is the name standing alone: not preceded or followed by a letter, a digit or a hyphen, so renaming
`lab-a` leaves `lab-ab`, `lab-a-b` and `pre-lab-a` as they are. The rewrite works on bytes, so a file's encoding,
byte order mark and line endings survive and a file that is not UTF-8 text is still handled correctly; a file
holding a NUL byte is binary and is left alone. The scope is the brain's own files:

- `.claude/skills/**` (the shipped `brain-*` skills too, only in the template: they are template-owned in a brain),
- `CLAUDE.md`, `README.md`, `docs/**` (not `docs/RETRO-LOG.md`, which is history), `scripts/**` and `brain.json`,
- in the template also `_meta/ROUTING-META.md` and `_meta/gates.json`, which name the shipped skills.

Symlinks, folders that are repos of their own, and `.git`, `node_modules`, `__pycache__` and virtualenv folders are
never entered, so nothing outside the brain is written. Every file is read and checked writable before anything
moves, so a refusal leaves the brain exactly as it was.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

from . import config, paths, routing_sync
from .config import Config, ConfigError
from .report import Finding, emit, exit_code
from .skills import SKILL_FILE, SKILLS_DIR, skills_dir

SKILLS_REL = "/".join(SKILLS_DIR)  # .claude/skills
HISTORY = "docs/RETRO-LOG.md"
SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", "venv"})
META_FILES = ("_meta/ROUTING-META.md", "_meta/gates.json")  # in scope in the template only
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class RenameError(Exception):
    """The rename was refused, or could not be carried out; the message says why."""


class _Change(NamedTuple):
    rel: str
    count: int
    data: bytes


def _folder(name: str) -> str:
    return f"{SKILLS_REL}/{name}"


def _moved(rel: str, src: str, dst: str) -> str:
    """Where the file at `rel` is once the folder `src` has become `dst`."""
    return dst + rel[len(src):] if rel == src or rel.startswith(src + "/") else rel


# -- what may be renamed ----------------------------------------------------------------------------


def _prefixes(cfg: Config) -> Tuple[str, ...]:
    """The prefixes a skill of this brain may be given: its own; in the template, the shipped and its own."""
    if cfg.role == "template":
        return ("brain", "template")
    return (cfg.prefix,) if cfg.prefix else ()


def _validate(root: Path, cfg: Config, old: str, new: str) -> None:
    if not _NAME.fullmatch(old):
        raise RenameError(f"OLD '{old}' is not a skill name (lowercase words joined by hyphens)")
    if old.startswith("brain-") and cfg.role != "template":
        raise RenameError(f"'{old}' is a shipped skill that the template owns, so a brain cannot rename it; "
                          f"propose the change upstream (docs/UPSTREAM.md) instead")
    if not _NAME.fullmatch(new):
        raise RenameError(f"NEW '{new}' is not a skill name (lowercase words joined by hyphens)")
    prefixes = _prefixes(cfg)
    if not prefixes:
        raise RenameError("brain.json has no prefix, so no name is available to a skill of this brain; set one first")
    if not any(re.fullmatch(re.escape(p) + r"(?:-[a-z0-9]+)+", new) for p in prefixes):
        raise RenameError(f"NEW '{new}' must start with {' or '.join(repr(p + '-') for p in prefixes)} "
                          f"and name something after it")
    if new == old:
        raise RenameError("NEW is the same as OLD")
    if not (skills_dir(root) / old / SKILL_FILE).is_file():
        raise RenameError(f"no skill '{old}' in {SKILLS_REL}")
    if os.path.lexists(str(skills_dir(root) / new)):
        raise RenameError(f"'{new}' already exists in {SKILLS_REL}")


# -- what is rewritten ------------------------------------------------------------------------------


def _candidates(root: Path, cfg: Config) -> List[str]:
    """The files in scope, as sorted posix paths relative to `root`. Whether each is text is for the reader."""
    in_template = cfg.role == "template"
    skills_base = str(skills_dir(root))
    found = {"CLAUDE.md", "README.md", "brain.json"}
    if in_template:
        found.update(META_FILES)
    for top in (skills_base, str(root / "docs"), str(root / "scripts")):
        for dirpath, dirnames, filenames in os.walk(top):  # symlinked folders are not followed
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in SKIP_DIRS
                and not os.path.lexists(os.path.join(dirpath, d, ".git"))  # a project repo of its own
                and not (dirpath == skills_base and d.startswith("brain-") and not in_template))
            for name in filenames:
                found.add(Path(os.path.relpath(os.path.join(dirpath, name), str(root))).as_posix())
    found.discard(HISTORY)
    real_root = os.path.realpath(str(root))
    files = []
    for rel in sorted(found):
        path = str(root / rel)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        real = os.path.realpath(path)
        if real == real_root or real.startswith(real_root + os.sep):
            files.append(rel)
    return files


def _changes(root: Path, cfg: Config, old: str, new: str) -> List[_Change]:
    """Validate, then work out every rewrite without making any. Raises RenameError on a refusal."""
    _validate(root, cfg, old, new)
    pattern = re.compile(rb"(?<![A-Za-z0-9-])" + re.escape(old.encode("ascii")) + rb"(?![A-Za-z0-9-])")
    replacement = new.encode("ascii")
    changes: List[_Change] = []
    for rel in _candidates(root, cfg):
        try:
            data = (root / rel).read_bytes()
        except OSError as why:
            raise RenameError(f"cannot read {rel} ({why.strerror or why}); nothing was changed")
        if b"\0" in data:
            continue
        rewritten, count = pattern.subn(lambda _match: replacement, data)
        if not count:
            continue
        if not os.access(str(root / rel), os.W_OK):
            raise RenameError(f"cannot write {rel}; make it writable and run again (nothing was changed)")
        changes.append(_Change(rel, count, rewritten))
    return changes


def plan(root: Path, cfg: Config, old: str, new: str) -> List[Tuple[str, int]]:
    """(path relative to `root`, replacements) for each file `apply` would rewrite, sorted by path. Writes nothing.
    Paths inside the skill's folder are given as they are now, under OLD. Raises RenameError on a refusal."""
    return [(change.rel, change.count) for change in _changes(Path(root), cfg, old, new)]


# -- carrying it out --------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(["git", "--no-optional-locks", *args], cwd=str(root), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def _tracked(root: Path, rel: str) -> bool:
    try:
        listed = _git(root, "ls-files", "-z", "--", rel)
    except OSError:  # no git here
        return False
    return listed.returncode == 0 and bool(listed.stdout)


def _move(root: Path, src: str, dst: str) -> None:
    if _tracked(root, src):
        moved = _git(root, "mv", "--", src, dst)
        if moved.returncode != 0:
            raise RenameError(f"git mv failed ({moved.stderr.strip() or 'no message'}); nothing was changed")
        return
    try:
        os.rename(str(root / src), str(root / dst))
    except OSError as why:
        raise RenameError(f"cannot move {src} to {dst} ({why.strerror or why}); nothing was changed")


def apply(root: Path, cfg: Config, old: str, new: str, problems: Optional[List[Finding]] = None) -> None:
    """Rename the skill: move its folder, rewrite what names it, then run `routing sync`.

    `problems` receives what the sync refused to write (a BROKEN finding each); the rename is done either way.
    Without a `problems` list a refused sync raises `routing_sync.SyncRefused`, after the rename is complete.
    Raises RenameError, before anything is changed, when the rename is refused.
    """
    root = Path(root)
    changes = _changes(root, cfg, old, new)
    src, dst = _folder(old), _folder(new)
    _move(root, src, dst)
    for index, change in enumerate(changes):
        rel = _moved(change.rel, src, dst)
        try:
            with open(str(root / rel), "wb") as handle:
                handle.write(change.data)
        except OSError as why:
            left = ", ".join(_moved(c.rel, src, dst) for c in changes[index:])
            raise RenameError(f"moved {src} to {dst}, but could not write {rel} ({why.strerror or why}); "
                              f"replace '{old}' with '{new}' by hand in: {left}, then run routing sync")
    try:
        cfg = config.load(root)  # the gates in brain.json may have changed under the old copy
    except ConfigError:
        pass
    routing_sync.sync(root, cfg, check=False, problems=problems)


# -- the command ------------------------------------------------------------------------------------


def add_arguments(parser) -> None:
    parser.add_argument("old", metavar="OLD", help="the skill's current name")
    parser.add_argument("new", metavar="NEW", help="its new name: this brain's prefix, then words joined by hyphens")
    parser.add_argument("--apply", action="store_true",
                        help="rename it; without this, only list what would change")


def _replacements(count: int) -> str:
    return f"{count} replacement" + ("" if count == 1 else "s")


def run(args) -> int:
    root = paths.harness_root()
    old, new = args.old, args.new
    src, dst = _folder(old), _folder(new)
    problems: List[Finding] = []
    try:
        cfg = config.load(root)
        files = plan(root, cfg, old, new)
        if not args.apply:
            print(f"would move   {src} -> {dst}")
            for rel, count in files:
                print(f"would edit   {rel}: {_replacements(count)}")
            print("then run routing sync, which rewrites each skill's Where this sits block")
            print(f"dry run: nothing was changed; run it again with --apply to rename {old} to {new}")
            return 0
        apply(root, cfg, old, new, problems)
    except (ConfigError, RenameError) as why:
        print(f"rename-skill: {why}", file=sys.stderr)
        return 1
    print(f"moved        {src} -> {dst}")
    for rel, count in files:
        print(f"edited       {_moved(rel, src, dst)}: {_replacements(count)}")
    emit(problems)
    if problems:
        print(f"renamed {old} to {new}, but routing sync left the files above as they were; fix them, "
              f"then run _meta/brain routing sync")
    else:
        print(f"renamed {old} to {new}; review it with git diff, then run _meta/brain lint")
    return exit_code(problems)
