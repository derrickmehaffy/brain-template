"""Shared test scaffolding: a temp root with a space in its path, a hermetic
git environment, and builders for fake brains and template copies."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent
VERSION = (TEMPLATE_ROOT / "_meta" / "VERSION").read_text(encoding="utf-8").strip()  # the template's version now

# Tests import the harness as `from brainlib import ...`.
_META = str(TEMPLATE_ROOT / "_meta")
if _META not in sys.path:
    sys.path.insert(0, _META)

_IGNORE_COPY = shutil.ignore_patterns("__pycache__", "*.pyc")

# Skipped when walking a template that is not a git repo (git mode needs no list:
# `git ls-files --exclude-standard` already leaves ignored scratch out).
_WALK_SKIP_ANYWHERE = {".git", "__pycache__"}
_WALK_SKIP_AT_ROOT = {"local", ".superpowers"}


class TempDirCase(unittest.TestCase):
    """Every test runs in `self.tmp`, a directory whose name contains a space."""

    def setUp(self) -> None:
        super().setUp()
        base = Path(tempfile.mkdtemp(prefix="brain-test-")).resolve()
        self.addCleanup(shutil.rmtree, str(base), True)
        self.tmp = base / "with space"
        self.tmp.mkdir()
        (self.tmp / "os-tmp").mkdir()
        (self.tmp / "home").mkdir()
        (self.tmp / "run").mkdir(mode=0o700)  # stands in for /run/user/<uid>: no test touches the real one
        empty_git_config = self.tmp / "gitconfig"
        empty_git_config.write_text("", encoding="utf-8")

        # Hermetic environment: no GIT_* leaks in from the caller, and neither the
        # person's global git config nor their global ignore file is read.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(
            GIT_AUTHOR_NAME="Brain Test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="Brain Test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
            GIT_CONFIG_GLOBAL=str(empty_git_config),
            GIT_CONFIG_NOSYSTEM="1",
            PYTHONDONTWRITEBYTECODE="1",
            TMPDIR=str(self.tmp / "os-tmp"),
            HOME=str(self.tmp / "home"),
            XDG_CONFIG_HOME=str(self.tmp / "home" / ".config"),
            XDG_RUNTIME_DIR=str(self.tmp / "run"),
        )
        self.env = env
        self._counter = 0

    # -- running things ---------------------------------------------------

    def run_brain(self, root, *args, stdin=None, cwd=None) -> subprocess.CompletedProcess:
        """Run `<root>/_meta/brain *args` and capture its text output."""
        root = Path(root)
        kwargs = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
        return subprocess.run(
            [sys.executable, str(root / "_meta" / "brain"), *args],
            cwd=str(cwd if cwd is not None else root),
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )

    def git(self, cwd, *args) -> str:
        """Run git in `cwd`; return stdout unchanged; raise AssertionError with stderr on failure."""
        r = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
        if r.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed ({r.returncode}): {r.stderr.strip()}")
        return r.stdout

    # -- builders ---------------------------------------------------------

    def _new_dir(self, label: str) -> Path:
        self._counter += 1
        path = self.tmp / f"{label}-{self._counter}"
        path.mkdir()
        return path

    def fake_brain(self, prefix="lab", role=None, extra=None) -> Path:
        """A brain folder holding the shipped harness and a minimal `brain.json`.

        Copies `_meta/` and every `.claude/skills/brain-*/` from the working tree.
        `role` is omitted from `brain.json` when None (so the loader's default
        applies); `extra` is merged over the top-level keys.
        """
        root = self._new_dir("brain")
        shutil.copytree(TEMPLATE_ROOT / "_meta", root / "_meta", ignore=_IGNORE_COPY)
        skills = TEMPLATE_ROOT / ".claude" / "skills"
        for folder in sorted(skills.glob("brain-*")):
            if folder.is_dir():
                shutil.copytree(folder, root / ".claude" / "skills" / folder.name, ignore=_IGNORE_COPY)
        raw = {"name": f"{prefix} test brain", "prefix": prefix, "description": "A brain for tests"}
        if role is not None:
            raw["role"] = role
        raw.update(extra or {})
        (root / "brain.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        return root

    def copy_template(self, with_local=True) -> Path:
        """A committed git copy of the template's working tree.

        Only files git would track (tracked, or untracked and not ignored) are
        copied, so ignored scratch (`local/`, `.superpowers/`, `.brain-private`)
        never leaks. The copy is a fresh repo on `main` with one commit, then has
        the pre-commit guard installed (as the real template does); `local/` is
        created empty afterwards when `with_local` is true.
        """
        dest = self._new_dir("template")
        self._copy_tree(TEMPLATE_ROOT, dest)
        self.git(dest, "init", "-q")
        self.git(dest, "symbolic-ref", "HEAD", "refs/heads/main")
        self.git(dest, "add", "-A")
        self.git(dest, "commit", "-q", "-m", "template copy for tests")
        installed = self.run_brain(dest, "hook", "install")
        if installed.returncode != 0:
            raise AssertionError(f"hook install failed in {dest}: {installed.stdout}{installed.stderr}")
        if with_local:
            (dest / "local").mkdir()
        return dest

    def make_brain(self, name="homelab", prefix="lab") -> Path:
        """A brain made by `new` from a fresh template copy, in a folder whose path contains a space."""
        template = self.copy_template()
        dest = self._new_dir("made")
        made = self.run_brain(template, "new", str(dest), "--name", name, "--prefix", prefix)
        if made.returncode != 0:
            raise AssertionError(f"new failed ({made.returncode}): {made.stdout}{made.stderr}")
        return dest

    def _copy_tree(self, src: Path, dest: Path) -> None:
        """Copy the files of `src` into `dest`: git's list when `src` is a repo, else a walk."""
        for rel in self._shipped_files(src):
            source = src / rel
            if not source.is_file():  # tracked but deleted in the working tree
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _shipped_files(self, src: Path) -> list[str]:
        if (src / ".git").exists():
            out = subprocess.run(
                ["git", "ls-files", "-co", "--exclude-standard", "-z"],
                cwd=str(src),
                env=self.env,
                capture_output=True,
                stdin=subprocess.DEVNULL,
            )
            if out.returncode != 0:
                raise AssertionError(f"git ls-files failed in {src}: {out.stderr.decode(errors='replace')}")
            return sorted(set(p for p in out.stdout.decode("utf-8").split("\0") if p))
        found = []
        for dirpath, dirnames, filenames in os.walk(str(src)):
            at_root = Path(dirpath) == src
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in _WALK_SKIP_ANYWHERE and not (at_root and d in _WALK_SKIP_AT_ROOT)
            )
            for name in filenames:
                found.append(os.path.relpath(os.path.join(dirpath, name), str(src)))
        return sorted(found)

    @staticmethod
    def make_skill(root, name, description, body) -> Path:
        """Write `.claude/skills/<name>/SKILL.md` under `root`; return the SKILL.md path."""
        path = Path(root) / ".claude" / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8")
        return path

    @staticmethod
    def snapshot(path) -> dict[str, tuple[int, int]]:
        """Relative path -> (size, mtime_ns) of every file under `path`, `.git` included."""
        path = Path(path)
        seen = {}
        for dirpath, _dirnames, filenames in os.walk(str(path)):
            for name in filenames:
                full = os.path.join(dirpath, name)
                st = os.lstat(full)
                seen[Path(os.path.relpath(full, str(path))).as_posix()] = (st.st_size, st.st_mtime_ns)
        return seen
