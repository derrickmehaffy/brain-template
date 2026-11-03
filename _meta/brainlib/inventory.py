"""Looking at a folder before it becomes a brain (spec §6, `adopt`): which git repositories are inside it, which
top-level folders are big, which of the files a brain keeps are already there, and what `git add -A` would stage.

Everything here only reads. It runs on real workspaces of tens of gigabytes with dozens of repositories, so:

- git is asked only questions that leave a repository's index alone (`gitutil` always passes
  `--no-optional-locks`), and never `git status`, which looks at every file;
- the search for repositories stops at the first `.git` it meets and does not follow links (`gitutil.nested_repos`);
- the staging preview uses a throwaway bare `GIT_DIR` in the OS temporary folder, so the folder is never written
  to, not even by an index git would otherwise create there. When the folder already is a repository, its own
  index is read (`ls-files`, never `status`) to find the tracked files the ignore rules would not hide.
"""
from __future__ import annotations

import os
import tempfile
import stat
from dataclasses import dataclass, field
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
    unreadable: List[str] = field(default_factory=list)  # folders (relative paths) that could not be read, sorted


def large_folder_mb() -> int:
    """The size, in MB, above which a top-level folder is large: `BRAIN_LARGE_FOLDER_MB` when it holds a whole
    number of at least 0, else `LARGE_FOLDER_MB`."""
    try:
        wanted = int(os.environ.get(LARGE_FOLDER_ENV, "").strip())
    except ValueError:
        return LARGE_FOLDER_MB
    return wanted if wanted >= 0 else LARGE_FOLDER_MB


# -- scanning -----------------------------------------------------------------------------------


def _tree_bytes(top: str, unreadable: List[str]) -> int:
    """The summed size of the files under `top`. Links are not followed (and not counted), and a file that cannot
    be read is skipped. A folder that cannot be listed is skipped too, so one locked-down folder does not stop the
    scan, but its path is added to `unreadable`: what is in it is not counted, and a repository in it is not found."""
    total = 0
    pending = [top]
    while pending:
        here = pending.pop()
        try:
            with os.scandir(here) as entries:
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
        except FileNotFoundError:  # gone since the parent was listed
            continue
        except OSError:
            unreadable.append(here)
    return total


def _large_folders(root: Path, unreadable: List[str]) -> List[Tuple[str, int]]:
    limit = large_folder_mb() * _MB
    found: List[Tuple[str, int]] = []
    try:
        with os.scandir(str(root)) as entries:
            tops = sorted((e.name, e.path) for e in entries if e.name != ".git" and not e.is_symlink()
                          and e.is_dir(follow_symlinks=False))
    except OSError:
        unreadable.append(str(root))
        return []
    for name, path in tops:
        size = _tree_bytes(path, unreadable)
        if size > limit:
            found.append((name, -(-size // _MB)))
    return sorted(found, key=lambda item: (-item[1], item[0]))


def scan(root) -> Inventory:
    """What is in `root`. Reads only: no file is written and no repository's index is touched."""
    root = Path(root)
    nested = [(repo.relative_to(root).as_posix(), gitutil.repo_state(repo)) for repo in gitutil.nested_repos(root)]
    existing = {key: (os.path.isdir(str(root / key)) if key in (".claude/skills", "docs")
                      else os.path.lexists(str(root / key))) for key in EXISTING}
    unreadable: List[str] = []
    large = _large_folders(root, unreadable)
    shown = sorted({"." if path == str(root) else Path(path).relative_to(root).as_posix() for path in unreadable})
    return Inventory(nested, large, existing, gitutil.is_repo(root), shown)


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


@dataclass(frozen=True)
class Preview:
    files: List[Tuple[str, int]]  # (path, size in bytes) of every file the brain would hold, sorted by path
    embedded: List[Tuple[str, bool]]  # (folder, has a commit): a repository the ignore rules let through
    tracked: List[str]  # paths in `files` the repository already tracks although the ignore rules hide them


def _names(raw: bytes) -> List[str]:
    # surrogateescape keeps a name that is not UTF-8 exact; a name is never split, so one with a newline survives.
    return [part.decode("utf-8", errors="surrogateescape") for part in raw.split(b"\0") if part]


def _size(root: Path, rel: str) -> int:
    """The size of the file at `rel`; -1 when it is gone. A folder (a tracked repository) counts as 0."""
    try:
        info = os.lstat(os.path.join(str(root), rel))
    except OSError:
        return -1
    return 0 if stat.S_ISDIR(info.st_mode) else info.st_size


def _tracked_as_repository(root: Path, folder: str) -> bool:
    """Whether the repository at `root` already tracks `folder` as a nested repository (a submodule entry)."""
    raw = gitutil.git(root, "ls-files", "--stage", "-z", "--", folder, check=False, binary=True)
    return any(name.split(" ", 1)[0] == gitutil.GITLINK_MODE for name in _names(raw))  # type: ignore[arg-type]


def preview(root, gitignore_text: str, root_is_repo: bool = False) -> Preview:
    """What `git add -A` would leave in the brain at `root` if its root `.gitignore` held `gitignore_text`.

    Git runs with a throwaway bare repository in the OS temporary folder as its `GIT_DIR`, `root` as its work
    tree and `gitignore_text` as `core.excludesFile`, so nothing is written in `root` and no repository in it is
    looked into. The folder's own `.gitignore` files apply as well, as they will once it is a brain; the
    person's global ignore file does not.

    - `files`: every file not ignored (a fresh index, so a tracked file is listed like any other), and, with
      `root_is_repo`, the files that repository tracks although the ignore rules hide them (`git add -A` stages
      a change to those, and ignore rules do not apply to a tracked file). Sorted by path.
    - `embedded`: a repository inside `root` that no ignore rule hides. It is not a file: `git add -A` would
      stage it as an embedded repository (which the pre-commit guard refuses), or, with no commit, fail. One the
      repository already tracks as a nested repository is left out.
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
        hidden: List[str] = []
        if root_is_repo:
            hidden = _names(gitutil.git(root, "-c", "core.excludesFile=" + excludes, "ls-files", "-c", "-i",
                                        "--exclude-standard", "-z", binary=True))  # type: ignore[arg-type]
    files: List[Tuple[str, int]] = []
    folders: List[str] = []
    for rel in _names(raw):  # type: ignore[arg-type]
        if rel.endswith("/"):  # a repository inside the folder
            folders.append(rel.rstrip("/"))
            continue
        size = _size(root, rel)
        if size >= 0:  # not gone since git looked
            files.append((rel, size))
    tracked: List[str] = []
    for rel in hidden:
        size = _size(root, rel)
        if size >= 0:
            files.append((rel, size))
            tracked.append(rel)
    embedded = [(folder, gitutil.short_sha(root / folder) is not None) for folder in folders
                if not (root_is_repo and _tracked_as_repository(root, folder))]
    return Preview(sorted(files), sorted(embedded), sorted(tracked))


def staging_preview(root: Path, gitignore_text: str) -> List[Tuple[str, int]]:
    """(path, size in bytes) of each file `git add -A` would stage in a fresh repository at `root` whose root
    `.gitignore` held `gitignore_text`, sorted by path (see `preview`; this is its `files` without the tracked
    ones). A repository inside `root` is not a file and is left out, and an ignored folder is not entered."""
    return preview(root, gitignore_text).files
