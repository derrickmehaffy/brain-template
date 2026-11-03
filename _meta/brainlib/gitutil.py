"""The one place the harness runs git.

Every call is an argument list handed to `git --no-optional-locks`, never a shell string, so a path with
spaces or shell characters is just an argument, and a read-only question leaves a repository's index alone
(a nested repo's `.git/index` is never refreshed by looking at it).
"""
from __future__ import annotations

import io
import os
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

GITLINK_MODE = "160000"  # a staged nested repository (a submodule entry)


class GitError(Exception):
    """git failed, or could not be run. `stderr` is what git said; `returncode` is None when git never ran."""

    def __init__(self, command: Tuple[str, ...], stderr: str, returncode: Optional[int] = None) -> None:
        self.command = command
        self.stderr = stderr
        self.returncode = returncode
        shown = " ".join(command[:3])
        super().__init__(f"git {shown} failed: {stderr.strip() or 'no message'}")


def _run(cwd, args: Tuple[str, ...]) -> subprocess.CompletedProcess:
    cwd = Path(cwd)
    if not cwd.is_dir():
        raise GitError(args, f"{cwd} is not a directory")
    try:
        return subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:  # git is not installed, or not executable
        raise GitError(args, f"cannot run git: {exc.strerror or exc}")


def git(cwd, *args: str, check: bool = True, binary: bool = False) -> Union[str, bytes]:
    """Run `git <args>` in `cwd`; return stdout (text decoded as UTF-8 with replacement, or bytes).

    With `check` (the default) a non-zero exit raises GitError carrying git's stderr; without it the
    stdout is returned whatever the exit status was (empty when git printed nothing).
    """
    done = _run(cwd, tuple(args))
    if check and done.returncode != 0:
        raise GitError(tuple(args), done.stderr.decode("utf-8", errors="replace"), done.returncode)
    return done.stdout if binary else done.stdout.decode("utf-8", errors="replace")


def _succeeds(cwd, *args: str) -> bool:
    try:
        return _run(cwd, tuple(args)).returncode == 0
    except GitError:
        return False


def _line(text: str) -> str:
    return text.split("\n", 1)[0].rstrip("\r")


# -- repositories -------------------------------------------------------------------


def is_repo(path) -> bool:
    """True when `path` is itself the top of a work tree (a `.git` folder, or the `.git` file of a linked
    worktree), not merely a folder somewhere inside one."""
    path = Path(path)
    return os.path.lexists(str(path / ".git")) and _succeeds(path, "rev-parse", "--git-dir")


def nested_repos(root) -> List[Path]:
    """Every folder below `root`, at any depth, that holds a `.git` file or folder. A repo found is not
    searched further. The root's own `.git` and symlinked folders are skipped."""
    root = Path(root)
    found: List[Path] = []
    for dirpath, dirnames, _filenames in os.walk(str(root)):
        kept = []
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            if name == ".git" or os.path.islink(full):
                continue
            if os.path.lexists(os.path.join(full, ".git")):
                found.append(Path(full))
            else:
                kept.append(name)
        dirnames[:] = kept
    return sorted(found)


@dataclass(frozen=True)
class RepoState:
    has_remote: bool
    unpushed: int  # commits on a local branch that no remote-tracking branch holds


def repo_state(path) -> RepoState:
    """Whether `path` has a remote, and how many commits exist only here (a repo with no remote has all of them
    unpushed). A repo git cannot read is reported as having neither."""
    has_remote = bool(str(git(path, "remote", check=False)).strip())
    counted = str(git(path, "rev-list", "--count", "--branches", "--not", "--remotes", check=False)).strip()
    return RepoState(has_remote, int(counted) if counted.isdigit() else 0)


def short_sha(path, ref: str = "HEAD") -> Optional[str]:
    """The abbreviated commit id `ref` names, or None (no such ref, no commits yet, not a repo)."""
    if ref.startswith("-"):
        return None
    out = _line(str(git(path, "rev-parse", "--verify", "--quiet", "--short", ref + "^{commit}", check=False)))
    return out or None


def _resolves(path, ref: str) -> bool:
    return _succeeds(path, "rev-parse", "--verify", "--quiet", ref + "^{commit}")


def default_branch(path) -> str:
    """The branch to read the repo's released state from: the one `origin/HEAD` points at, else `main`, else
    `master`, else `HEAD` (whatever is checked out).

    It returns the LOCAL branch `origin/HEAD` names (`main`, not `origin/main`) whenever that branch exists. That
    is deliberate: a template developer's local commits should reach the brains that read this branch without a
    push first. The remote-tracking ref is the fallback only when there is no such local branch."""
    target = _line(str(git(path, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False)))
    if target:
        name = target[len("origin/"):] if target.startswith("origin/") else target
        for candidate in (name, target):  # the local branch when there is one, else the remote-tracking ref
            if _resolves(path, candidate):
                return candidate
    for name in ("main", "master"):
        if _resolves(path, "refs/heads/" + name):
            return name
    return "HEAD"


def archive(src, ref: str) -> Dict[str, Tuple[bytes, int]]:
    """The files of commit `ref` in the repo at `src`: relative path -> (content, mode). The mode is 0o755 when
    the file is executable, else 0o644; directories and symlinks are left out."""
    if ref.startswith("-"):
        raise GitError(("archive", ref), "a ref must not start with '-'")
    data = git(src, "archive", "--format=tar", ref, binary=True)
    files: Dict[str, Tuple[bytes, int]] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        for member in tar:
            if not member.isfile():
                continue
            handle = tar.extractfile(member)
            content = handle.read() if handle is not None else b""
            files[member.name] = (content, 0o755 if member.mode & 0o111 else 0o644)
    return files


# -- the index -------------------------------------------------------------------------


def _split_names(raw: bytes) -> List[str]:
    # surrogateescape keeps a name that is not UTF-8 exact, and subprocess sends it back as the same bytes.
    return [part.decode("utf-8", errors="surrogateescape") for part in raw.split(b"\0") if part]


def staged(root) -> List[str]:
    """The paths staged to be added, copied, modified or renamed (deletions are not listed)."""
    # --ignore-submodules=none: a user's diff.ignoreSubmodules would otherwise hide a staged nested repo.
    raw = git(root, "diff", "--cached", "--ignore-submodules=none", "--name-only", "-z", "--diff-filter=ACMR",
              binary=True)
    return _split_names(raw)  # type: ignore[arg-type]


@dataclass(frozen=True)
class StagedEntry:
    path: str
    status: str  # A added, C copied, M modified, T type changed, D deleted
    mode: str  # the staged mode ("100644", "120000", GITLINK_MODE, ...); "000000" for a deletion


def staged_entries(root) -> List[StagedEntry]:
    """Every staged change, deletions included, with its mode. Renames appear as a deletion and an addition."""
    raw = git(root, "diff", "--cached", "--ignore-submodules=none", "--raw", "-z", "--no-renames", binary=True)
    tokens = raw.split(b"\0")  # type: ignore[union-attr]
    entries: List[StagedEntry] = []
    i = 0
    while i + 1 < len(tokens):
        meta = tokens[i].decode("ascii", errors="replace")
        if meta.startswith(":"):
            fields = meta[1:].split()
            if len(fields) >= 5:
                path = tokens[i + 1].decode("utf-8", errors="surrogateescape")
                entries.append(StagedEntry(path, fields[4][:1], fields[1]))
            i += 2
        else:
            i += 1
    return entries


def staged_blob(root, path: str) -> bytes:
    """The staged (index) content of `path`, not the working-tree file."""
    return git(root, "cat-file", "blob", ":0:" + path, binary=True)  # type: ignore[return-value]


def staged_size(root, path: str) -> int:
    """The size in bytes of the staged content of `path`."""
    return int(str(git(root, "cat-file", "-s", ":0:" + path)).strip())
