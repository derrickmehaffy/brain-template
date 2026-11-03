"""Looking at a folder before it becomes a brain (spec §6, `adopt`): which git repositories are inside it, which
top-level folders are big, which of the files a brain keeps are already there, and what `git add -A` would stage.

Everything here only reads. It runs on real workspaces of tens of gigabytes with dozens of repositories, so:

- git is asked only questions that leave a repository's index alone (`gitutil` always passes
  `--no-optional-locks`), and never `git status`, which looks at every file;
- the search for repositories stops at the first `.git` it meets and does not follow links (`gitutil.nested_repos`);
- the staging preview uses a throwaway bare `GIT_DIR` in the OS temporary folder, so the folder is never written
  to, not even by an index git would otherwise create there.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from . import gitutil

LARGE_FOLDER_MB = 100  # a top-level folder over this many MB is reported as large
LARGE_FOLDER_ENV = "BRAIN_LARGE_FOLDER_MB"  # overrides it (the tests set it small)
_MB = 1024 * 1024

# What `existing` reports on: path relative to the folder -> how it reads in the inventory.
EXISTING = {".claude/skills": ".claude/skills/", "CLAUDE.md": "CLAUDE.md", "docs": "docs/", ".env": ".env"}


@dataclass(frozen=True)
class Inventory:
    nested: List[Tuple[str, gitutil.RepoState]]  # (path relative to the folder, state), sorted by path
    large: List[Tuple[str, int]]  # (top-level folder, size in MB rounded up), biggest first
    existing: Dict[str, bool]  # EXISTING key -> whether the folder already has it
    root_is_repo: bool  # the folder itself already is a git repository


def large_folder_mb() -> int:
    """The size, in MB, above which a top-level folder is large: `BRAIN_LARGE_FOLDER_MB` when it holds a whole
    number of at least 0, else `LARGE_FOLDER_MB`."""
    try:
        wanted = int(os.environ.get(LARGE_FOLDER_ENV, "").strip())
    except ValueError:
        return LARGE_FOLDER_MB
    return wanted if wanted >= 0 else LARGE_FOLDER_MB


# -- scanning -----------------------------------------------------------------------------------


def _tree_bytes(top: str) -> int:
    """The summed size of the files under `top`. Links are not followed (and not counted), and a folder or file
    that cannot be read is skipped, so one locked-down folder does not stop the scan."""
    total = 0
    pending = [top]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _large_folders(root: Path) -> List[Tuple[str, int]]:
    limit = large_folder_mb() * _MB
    found: List[Tuple[str, int]] = []
    try:
        with os.scandir(str(root)) as entries:
            tops = sorted((e.name, e.path) for e in entries if e.name != ".git" and not e.is_symlink()
                          and e.is_dir(follow_symlinks=False))
    except OSError:
        return []
    for name, path in tops:
        size = _tree_bytes(path)
        if size > limit:
            found.append((name, -(-size // _MB)))
    return sorted(found, key=lambda item: (-item[1], item[0]))


def scan(root) -> Inventory:
    """What is in `root`. Reads only: no file is written and no repository's index is touched."""
    root = Path(root)
    nested = [(repo.relative_to(root).as_posix(), gitutil.repo_state(repo)) for repo in gitutil.nested_repos(root)]
    existing = {key: (os.path.isdir(str(root / key)) if key in (".claude/skills", "docs")
                      else os.path.lexists(str(root / key))) for key in EXISTING}
    return Inventory(nested, _large_folders(root), existing, gitutil.is_repo(root))


def _describe(state: gitutil.RepoState) -> str:
    text = "remote" if state.has_remote else "no remote"
    return f"{text}, {state.unpushed} unpushed" if state.unpushed else text


def render(inv: Inventory) -> str:
    """The inventory as lines of text, no trailing newline."""
    lines = [f"root git repo: {'yes' if inv.root_is_repo else 'no'}"]
    if inv.nested:
        lines.append(f"nested git repos: {len(inv.nested)}")
        lines.extend(f"  {path}: {_describe(state)}" for path, state in inv.nested)
    else:
        lines.append("nested git repos: none")
    heading = f"large top-level folders (over {large_folder_mb()} MB)"
    if inv.large:
        lines.append(heading + ":")
        lines.extend(f"  {name}: {mb} MB" for name, mb in inv.large)
    else:
        lines.append(heading + ": none")
    there = [label for key, label in EXISTING.items() if inv.existing.get(key)]
    lines.append("already there: " + (", ".join(there) if there else "nothing"))
    return "\n".join(lines)


# -- what `git add -A` would stage ---------------------------------------------------------------


def staging_preview(root: Path, gitignore_text: str) -> List[Tuple[str, int]]:
    """(path, size in bytes) of each file `git add -A` would stage in a fresh repository at `root` whose root
    `.gitignore` held `gitignore_text`, sorted by path. A repository inside `root` is not a file and is left out
    (git shows it as `dir/`), and an ignored folder is not entered.

    Git runs with a throwaway bare repository in the OS temporary folder as its `GIT_DIR`, `root` as its work
    tree and `gitignore_text` as `core.excludesFile`, so nothing is written in `root` and no repository in it is
    looked into. The folder's own `.gitignore` files apply as well, as they will once it is a brain; the
    person's global ignore file does not.
    """
    root = Path(root)
    with tempfile.TemporaryDirectory(prefix="brain-adopt-") as scratch:
        git_dir = os.path.join(scratch, "preview.git")
        excludes = os.path.join(scratch, "excludes")
        with open(excludes, "w", encoding="utf-8", newline="") as handle:
            handle.write(gitignore_text)
        gitutil.git(scratch, "init", "-q", "--bare", git_dir)
        raw = gitutil.git(root, "--git-dir=" + git_dir, "--work-tree=" + str(root), "-c",
                          "core.excludesFile=" + excludes, "ls-files", "-o", "--exclude-standard", "-z",
                          binary=True)
    found: List[Tuple[str, int]] = []
    for part in raw.split(b"\0"):  # type: ignore[union-attr]
        if not part:
            continue
        rel = part.decode("utf-8", errors="surrogateescape")
        if rel.endswith("/"):  # a nested repository
            continue
        try:
            found.append((rel, os.lstat(os.path.join(str(root), rel)).st_size))
        except OSError:  # gone since git looked
            continue
    return sorted(found)
