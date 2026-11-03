"""Builders for test folders that look like the ones `adopt` is aimed at: a workspace that already holds notes,
a skill, an `.env`, a big asset folder and several git repositories at different depths.

Everything is built with git commands in a hermetic environment (no person's config is read), and no repository
needs a network: a "remote" is a configured URL plus a remote-tracking ref, so "pushed" is whatever that ref holds.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, Optional

MIB = 1024 * 1024

# What the files the person already has contain; tests compare against these bytes after `adopt` has run.
CLAUDE_MD = "existing notes\n"
GITIGNORE = "*.log\n"
ENV = "API_KEY=fixture-value\n"
NOTES = "# Notes\n\nkept exactly as they are\n"
SKILL = ("---\nname: se2-idea\ndescription: Captures an idea. Use when the person has one.\n---\n"
         "Write the idea down.\n")
SKILL_PATH = ".claude/skills/se2-idea/SKILL.md"


def git_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """`base` (default: the process environment) without any GIT_* variable, with a fixed identity, and with
    neither the person's global git config nor the system one."""
    env = {k: v for k, v in (os.environ if base is None else base).items() if not k.startswith("GIT_")}
    env.update(
        GIT_AUTHOR_NAME="Fixture",
        GIT_AUTHOR_EMAIL="fixture@example.invalid",
        GIT_COMMITTER_NAME="Fixture",
        GIT_COMMITTER_EMAIL="fixture@example.invalid",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    return env


def _git(cwd: Path, env: Dict[str, str], *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {cwd}: {done.stderr.decode(errors='replace')}")
    return done.stdout.decode("utf-8", errors="replace")


def _commit(repo: Path, env: Dict[str, str], message: str) -> None:
    (repo / "log.txt").write_text(message + "\n", encoding="utf-8")
    _git(repo, env, "add", "-A")
    _git(repo, env, "commit", "-q", "-m", message)


def make_repo(path: Path, env: Dict[str, str], commits: int = 1, remote: bool = False, pushed: int = 0) -> Path:
    """A repository at `path` with `commits` commits. With `remote`, `origin` is configured and its remote-tracking
    branch points at the first `pushed` commits (0 = none of them), so the rest count as unpushed."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, env, "init", "-q")
    _git(path, env, "symbolic-ref", "HEAD", "refs/heads/main")
    if remote:
        _git(path, env, "remote", "add", "origin", "https://example.invalid/" + path.name + ".git")
    for number in range(1, commits + 1):
        _commit(path, env, f"{path.name} commit {number}")
        if remote and number == pushed:
            _git(path, env, "update-ref", "refs/remotes/origin/main", "HEAD")
    return path


def build_workspace(root, env: Optional[Dict[str, str]] = None) -> dict:
    """Fill `root` (made when missing) with the folder a person who has worked with Claude for a while has.

    - `alpha/`: a repository with a remote and nothing unpushed; `beta/`: one with no remote;
      `work/team/gamma/`: one with a remote and two commits that are not on it (two levels below the top)
    - `Assets/`: a 2 MiB file
    - `CLAUDE.md` ("existing notes"), `.gitignore` (`*.log`), `.env` (`API_KEY=fixture-value`),
      `.claude/skills/se2-idea/SKILL.md`, `docs/notes.md`

    `env` is the environment git runs in (default: hermetic, see `git_env`). Returns the facts a test checks:
    `root`, `nested` (role -> path relative to root), `unpushed` (path -> commits no remote holds), `large`
    (folder name), `large_mb`, and `files` (path -> the bytes written, for the files the person already had).
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    env = git_env() if env is None else env

    make_repo(root / "alpha", env, commits=2, remote=True, pushed=2)
    make_repo(root / "beta", env, commits=1)
    make_repo(root / "work" / "team" / "gamma", env, commits=3, remote=True, pushed=1)

    (root / "Assets").mkdir()
    (root / "Assets" / "big.bin").write_bytes(b"\0" * (2 * MIB))

    files = {
        "CLAUDE.md": CLAUDE_MD.encode("utf-8"),
        ".gitignore": GITIGNORE.encode("utf-8"),
        ".env": ENV.encode("utf-8"),
        SKILL_PATH: SKILL.encode("utf-8"),
        "docs/notes.md": NOTES.encode("utf-8"),
    }
    for rel, data in files.items():
        target = root.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    return {
        "root": root,
        "nested": {"remote": "alpha", "local": "beta", "deep": "work/team/gamma"},
        "unpushed": {"alpha": 0, "beta": 1, "work/team/gamma": 2},
        "large": "Assets",
        "large_mb": 2,
        "files": files,
    }
