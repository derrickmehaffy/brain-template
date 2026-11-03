"""`brain init`: turn a copy of the template into a brain, in place (spec §6).

This is the one command that deletes files (the template-only paths) and replaces a repository's history, so every
refusal runs before anything changes: not a template copy, a template checkout (`local/`), a linked worktree, a
dirty tree, commits or a stash that exist only here, a hook the guard could not be installed beside. The last
refusal is a rehearsal: the whole conversion, first commit and pre-commit guard included, is done in a temporary
copy of the folder, and only a rehearsal that went through lets the real one start. After that:

1. History. A plain clone of the template has the template's commits and its `origin`; its `.git` is MOVED to
   `.brain/template-history.git` (never deleted, so it stays recoverable) and a fresh repository is started. A repo
   made with "Use this template" keeps its own history; a folder with no repository gets one.
2. The template-only paths are removed, then the skeleton, `brain.json`, the managed blocks and settings, the
   manifest and the practices index are written, the pre-commit guard installed and the first commit made.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple
from urllib.parse import unquote, urlparse

from . import config, gitutil, hook, install, managed, manifest, paths
from .report import WARN, Finding, emit

# What a copy of the template holds that a brain never does (spec §3). Relative to the root, `/`-separated; a path
# with a glob character names several. `docs`, `CLAUDE.md`, `README.md`, `.gitignore`, `brain.json` and the
# settings are not kept: the brain gets its own from the skeleton.
TEMPLATE_ONLY = [".claude/skills/template-*", "tests", "docs", "CLAUDE.md", "README.md", ".gitignore",
                 ".claude/settings.json", "brain.json"]

HISTORY_DIR = ".brain/template-history.git"
# How the history of the copy is handled.
MOVE, KEEP, CREATE = "move", "keep", "create"

_EXPECTED = (install.InstallError, managed.ManagedError, hook.HookError, config.ConfigError, gitutil.GitError, OSError)
# Variables that point git at one particular repository. Set (a git hook exports them), they would send `git init`
# and the first commit to that repository instead of this one.
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
                      "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")
_GLOB_CHARS = re.compile(r"[*?\[]")
_SHOWN_PATHS = 5


def add_arguments(parser) -> None:
    parser.add_argument("--name", required=True, help="the brain's name")
    parser.add_argument("--prefix", required=True, help="the prefix of the brain's own skills (e.g. lab for lab-*)")
    parser.add_argument("--description", default="", help="one line on what the brain is for")
    parser.add_argument("--python", default="python3", metavar="PATH",
                        help="the interpreter the brain's scripts and tests run with (default: python3)")
    parser.add_argument("--packages", choices=config.PACKAGE_POLICIES, default="stdlib-only",
                        help="whether the brain's scripts may use packages (default: stdlib-only)")
    parser.add_argument("--private", action="append", default=[], metavar="PATTERN",
                        help="a regular expression that must never be committed; written to .brain-private "
                             "(repeatable)")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be removed and written, and change nothing")


def _refuse(message: str) -> int:
    print(f"init: {message}", file=sys.stderr)
    return 1


# -- is this a plain clone of the template? ---------------------------------------------------------


def _origin(root: Path) -> Optional[str]:
    """The URL or path of the `origin` remote as recorded, or None."""
    out = str(gitutil.git(root, "config", "--get", "remote.origin.url", check=False)).strip()
    return out or None


def _local_path(root: Path, location: str) -> Optional[Path]:
    """The folder `location` (a remote's URL) names on this machine: a path, or a `file://` URL. None for any other
    URL, and for a path that is not a folder."""
    if location.startswith("file://"):
        location = unquote(urlparse(location).path)
    elif "://" in location:
        return None
    candidate = Path(location)
    if not candidate.is_absolute():
        candidate = root / candidate  # git reads a relative remote from the repository's top
    return candidate if candidate.is_dir() else None


def _normal(location: str) -> str:
    text = location.strip().rstrip("/")
    return text[:-len(".git")] if text.endswith(".git") else text


def _same_location(root: Path, a: str, b: str) -> bool:
    if _normal(a) == _normal(b):
        return True
    local_a, local_b = _local_path(root, a), _local_path(root, b)
    return local_a is not None and local_b is not None and os.path.realpath(str(local_a)) == os.path.realpath(
        str(local_b))


def _is_template_folder(folder: Path) -> bool:
    try:
        return config.read_raw(folder).get("role") == "template"
    except config.ConfigError:
        return False


def is_plain_clone(root, cfg) -> bool:
    """True when `root` is a repository whose `origin` is the template itself: the template's canonical
    `template.source` (from `cfg`, the template's own brain.json), or a local folder whose `brain.json` has
    `role: template`. A repo made with "Use this template" has the person's own repository as `origin`, so it is
    not one; neither is a folder with no repository, or a repository with no `origin`."""
    root = Path(root)
    if not gitutil.is_repo(root):
        return False
    origin = _origin(root)
    if origin is None:
        return False
    if cfg.template_source and _same_location(root, origin, cfg.template_source):
        return True
    local = _local_path(root, origin)
    return local is not None and _is_template_folder(local)


# -- refusals --------------------------------------------------------------------------------------


def _args_problem(args) -> Optional[str]:
    problem = config.validate_prefix(args.prefix)
    if problem:
        return problem
    for label, value in (("name", args.name), ("description", args.description)):
        if "\n" in value or "\r" in value:
            return f"the {label} must be one line"
    if not args.name.strip():
        return "the name must not be empty"
    for pattern in args.private:
        reason = install.private_pattern_problem(pattern)
        if reason:
            return f"--private: a pattern {reason}"
    return None


def _shown(names: List[str]) -> str:
    head = ", ".join(names[:_SHOWN_PATHS])
    return head + (f" and {len(names) - _SHOWN_PATHS} more" if len(names) > _SHOWN_PATHS else "")


def _repo_problem(root: Path) -> Optional[str]:
    """Why an existing `.git` rules out turning this folder into a brain, or None (also when there is none)."""
    dotgit = root / ".git"
    if not os.path.lexists(str(dotgit)):
        return None
    if dotgit.is_symlink() or not dotgit.is_dir():
        return (".git here is a file or a link (a linked worktree or a submodule), not a repository folder; init "
                "needs a plain copy of the template, one it may replace the history of")
    if not gitutil.is_repo(root):
        return ".git here is not a repository git can read; repair or remove it, then run init again"
    if not gitutil.short_sha(root):
        return "the repository has no commit; commit the copy as it is, then run init again"
    changes = [line[3:] for line in str(gitutil.git(root, "status", "--porcelain", "--untracked-files=normal",
                                                    "--ignore-submodules=none")).splitlines() if line.strip()]
    if changes:
        return (f"the working tree has uncommitted changes ({_shown(changes)}); commit or discard them, then run "
                "init again")
    return None


def _clone_problem(root: Path) -> Optional[str]:
    """Why the history of a plain clone may not be replaced, or None: a commit or a stash that exists only here is
    refused (the moved repository would hold the only copy), and so is a history folder already in the way."""
    unpushed = str(gitutil.git(root, "rev-list", "--count", "HEAD", "--branches", "--not", "--remotes")).strip()
    if unpushed.isdigit() and int(unpushed) > 0:
        return (f"{unpushed} commit{'s' if unpushed != '1' else ''} exist only in this clone (on no remote); push "
                "them first, so no history is lost when init starts a new one")
    if str(gitutil.git(root, "stash", "list")).strip():
        return "git stash holds changes; apply or drop them first, so nothing is left behind in the old history"
    folder = root / ".brain"
    if os.path.lexists(str(folder)) and (folder.is_symlink() or not folder.is_dir()):
        return ".brain exists and is not a folder; move it aside, then run init again"
    if os.path.lexists(str(root / HISTORY_DIR)):
        return f"{HISTORY_DIR} already exists; move it aside, then run init again"
    return None


def _hooks_path_problem(root: Path, mode: str) -> Optional[str]:
    """Git runs the guard from `<repo>/.git/hooks`, which it ignores while `core.hooksPath` is set. A repo that is
    kept answers for its own config; one that is started fresh inherits only the global and system settings, which
    a scratch folder shows."""
    if mode == KEEP:
        configured = str(gitutil.git(root, "config", "--get", "core.hooksPath", check=False)).strip()
    else:
        with tempfile.TemporaryDirectory(prefix="brain-init-") as scratch:
            configured = str(gitutil.git(scratch, "config", "--get", "core.hooksPath", check=False)).strip()
    if configured:
        return (f"core.hooksPath is set ({configured}), so git would never run the brain's pre-commit guard; "
                "unset it, or call `_meta/brain hook pre-commit` from the hook that path holds, then run init again")
    return None


def _foreign_hook_problem(root: Path) -> Optional[str]:
    """A repo that is kept may hold a pre-commit hook of its own, which `hook.install` would refuse to replace."""
    common = str(gitutil.git(root, "rev-parse", "--git-common-dir")).rstrip("\n")
    target = (root / common).resolve() / "hooks" / "pre-commit"
    if os.path.lexists(str(target)):
        try:
            same = target.read_bytes() == hook.SHIM.encode("utf-8")
        except OSError as exc:
            return f"cannot read the existing {target}: {exc.strerror or exc}"
        if not same:
            return (f"{target} is a pre-commit hook of your own, not the brain template's shim; move it aside and "
                    "run init again, or keep it and have it run `_meta/brain hook pre-commit`")
    return None


def _template_only_present(root: Path) -> List[str]:
    """The `TEMPLATE_ONLY` paths that exist, as `/`-separated paths from the root, sorted within each entry."""
    found: List[str] = []
    for entry in TEMPLATE_ONLY:
        if _GLOB_CHARS.search(entry):
            matches = glob.glob(os.path.join(glob.escape(str(root)), *entry.split("/")))
            found.extend(sorted(os.path.relpath(match, str(root)).replace(os.sep, "/") for match in matches))
        elif os.path.lexists(str(root / entry)):
            found.append(entry)
    return found


def _link_problem(root: Path, present: List[str]) -> Optional[str]:
    """A template-only path is removed with `rmtree` or `unlink`; one whose parent folder is a link leading outside
    the root would reach files that are not this copy's."""
    base = os.path.realpath(str(root))
    for rel in present:
        parent = os.path.realpath(os.path.dirname(str(root / rel)))
        if parent != base and not parent.startswith(base + os.sep):
            return (f"{rel} is reached through a link that leads outside this folder; init removes only files "
                    "inside the copy. Replace the link with the folder it points to, then run init again")
    return None


def _preflight(root: Path, cfg: config.Config, args) -> Tuple[Optional[str], str]:
    """(the first reason init must refuse or None, how the history is handled). Nothing is changed."""
    if cfg.role != "template":
        return ('run init in a copy of the template; this folder is a brain (its brain.json does not have '
                '"role": "template")'), KEEP
    if os.path.lexists(str(root / "local")):
        return ("local/ exists, so this is the template's own checkout, not a copy of it, and init would delete the "
                "template's files; to make a brain from the template use new or adopt there"), KEEP
    problem = _args_problem(args) or _repo_problem(root)
    if problem:
        return problem, KEEP
    if not os.path.lexists(str(root / ".git")):
        mode = CREATE
    else:
        mode = MOVE if is_plain_clone(root, cfg) else KEEP
    problem = _clone_problem(root) if mode == MOVE else None
    problem = problem or _hooks_path_problem(root, mode)
    if mode == KEEP:
        problem = problem or _foreign_hook_problem(root)
    return problem or _link_problem(root, _template_only_present(root)), mode


# -- the plan ----------------------------------------------------------------------------------------


class _Plan(NamedTuple):
    shipped: install.Files  # the template-owned files, already in place
    filled: install.Files  # the skeleton with the name, prefix and description filled in
    raw: dict  # the new brain.json
    version: str  # `<VERSION>+<sha>` of the copy's HEAD before its history moves


def _plan(args, root: Path, cfg: config.Config, mode: str) -> _Plan:
    """What to write, from the copy's committed files."""
    files = install.template_files(root)
    shipped = install.shipped(files)
    starter = install.skeleton(files)
    if "_meta/brain" not in shipped or not starter:
        raise install.InstallError(f"{root} does not hold a harness and a skeleton (_meta/brain, _meta/skeleton/); "
                                   "is it a copy of the brain template?")
    version = install.version_string(root)  # before the history moves: HEAD is the copy's own
    name, description = args.name.strip(), args.description.strip()
    values = {"name": name, "prefix": args.prefix, "description": description}
    filled = {rel: (install.fill(data, values), bits) for rel, (data, bits) in starter.items()}
    source = _origin(root) if mode == MOVE else cfg.template_source
    raw = install.new_brain_json(name, args.prefix, description, source, version, args.python, args.packages,
                                 bool(args.private))
    return _Plan(shipped, filled, raw, version)


def _paths_written(plan: _Plan, private: bool) -> List[str]:
    extra = ["brain.json", manifest.MANIFEST_PATH, "docs/practices/INDEX.md"]
    if private:
        extra.append(config.PRIVATE_FILE)
    return sorted(set(plan.filled) | set(extra))


_HISTORY_LINE = {
    MOVE: f"move .git to {HISTORY_DIR} (the template's history, kept so nothing is lost), then run git init",
    KEEP: "keep the history this repository has; the first commit goes on top of it",
    CREATE: "run git init (this folder is not a repository)",
}


def _dry_run(root: Path, plan: _Plan, mode: str, present: List[str], written: List[str], message: str) -> int:
    print(f"dry run: nothing is changed. init would turn {root} into a brain from template v{plan.version}:")
    print(f"  history: {_HISTORY_LINE[mode]}")
    for rel in present:
        print(f"  remove {rel}")
    for rel in written:
        print(f"  write {rel}")
    print(f"then it would install the pre-commit guard and make the first commit:\n  {message}")
    print("rehearsed in a temporary copy, since discarded: the whole conversion, first commit and pre-commit guard "
          "included, went through")
    return 0


# -- doing it ------------------------------------------------------------------------------------------


def _remove(root: Path, rel: str) -> None:
    target = root / rel
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(str(target))
    else:
        os.unlink(str(target))


def _start_history(root: Path, mode: str) -> None:
    if mode == MOVE:
        (root / ".brain").mkdir(exist_ok=True)
        os.rename(str(root / ".git"), str(root / HISTORY_DIR))  # a move on one filesystem: nothing is copied or lost
    if mode in (MOVE, CREATE):
        install.git_init(root)


def _convert(target: Path, mode: str, plan: _Plan, present: List[str], args) -> List[str]:
    """Everything up to the first commit, in `target`. Returns the warnings."""
    _start_history(target, mode)
    for rel in present:
        _remove(target, rel)
    install.write_tree(target, plan.filled, overwrite=False)
    config.write_raw(target, plan.raw)
    warnings = install.apply_managed(target)
    if args.private:
        install.write_private(target, args.private)
    manifest.write(target, sorted(plan.shipped))
    install.write_practices_index(target)
    hook.install(target)
    return warnings


def _git_detail(exc: gitutil.GitError) -> str:
    return "\n".join("  " + line for line in exc.stderr.strip().splitlines()) or f"  {exc}"


def _rehearse(root: Path, mode: str, plan: _Plan, present: List[str], args, message: str) -> Optional[str]:
    """Do the whole conversion, the first commit and the pre-commit guard included, in a copy of the folder under the
    OS temporary folder, then discard the copy. None when it all went through, else why it would not. The folder
    itself is only read. A copy that is to get a fresh repository is copied without its `.git`, which would be
    moved away; one that keeps its history takes its `.git` along, so the commit is made on top of it."""
    base = os.path.realpath(str(root))
    try:
        scratch = Path(tempfile.mkdtemp(prefix="brain-init-"))
    except OSError as exc:
        return f"cannot make a temporary folder to rehearse in: {exc.strerror or exc}"
    try:
        if os.path.realpath(str(scratch)).startswith(base + os.sep):
            return (f"the temporary folder {scratch} is inside this folder; point TMPDIR somewhere else and run "
                    "init again")
        at_root = {".brain"} | (set() if mode == KEEP else {".git"})  # left out of the copy, at the top only

        def leave_out(folder, names):
            skipped = {name for name in names if name == "__pycache__"}
            return skipped | (at_root & set(names) if os.path.realpath(folder) == base else set())

        copy = scratch / "copy"
        shutil.copytree(str(root), str(copy), symlinks=True, ignore=leave_out)
        _convert(copy, KEEP if mode == KEEP else CREATE, plan, present, args)
        try:
            install.first_commit(copy, message)
        except gitutil.GitError as exc:
            return f"the first commit would fail:\n{_git_detail(exc)}"
    except _EXPECTED as exc:
        return str(exc)
    finally:
        shutil.rmtree(str(scratch), ignore_errors=True)
    return None


def _stopped(root: Path, mode: str, message: str) -> int:
    """Stop after the copy has been changed (a failure the rehearsal did not foresee): what was done stays, so the
    person can read it and finish by hand."""
    print(f"init: {message}", file=sys.stderr)
    where = (f"the template's history is in {root / HISTORY_DIR} (read it with `git --git-dir={HISTORY_DIR} log`); "
             if mode == MOVE else "")
    print(f"init: {where}what was done is still in {root}; fix the cause and finish by hand (commit everything "
          "with the message above)", file=sys.stderr)
    return 1


def run(args) -> int:
    for name in _GIT_LOCATION_VARS:
        os.environ.pop(name, None)
    root = paths.harness_root()
    try:
        cfg = config.load(root)
        problem, mode = _preflight(root, cfg, args)
        if problem:
            return _refuse(problem)
        plan = _plan(args, root, cfg, mode)
        present = _template_only_present(root)
        message = f"meta(brain): initialise from template v{plan.version}"
        problem = _rehearse(root, mode, plan, present, args, message)
    except _EXPECTED as exc:
        return _refuse(str(exc))
    if problem:
        return _refuse(f"rehearsed in a temporary copy, the conversion would fail, so nothing was changed:\n{problem}")

    written = _paths_written(plan, bool(args.private))
    if args.dry_run:
        return _dry_run(root, plan, mode, present, written, message)

    try:
        warnings = _convert(root, mode, plan, present, args)
    except _EXPECTED as exc:
        return _stopped(root, mode, f"stopped before the first commit: {exc}")
    emit([Finding(WARN, "init", w) for w in warnings])
    try:
        sha = install.first_commit(root, message)
    except gitutil.GitError as exc:
        return _stopped(root, mode, f"the first commit failed:\n{_git_detail(exc)}\nthe message is: {message}")
    except OSError as exc:
        return _stopped(root, mode, f"the first commit failed: {exc.strerror or exc}\nthe message is: {message}")

    print(f"removed {len(present)} template-only paths and wrote {len(written)} files in {root}")
    print(f"first commit {sha}: {message}")
    if mode == MOVE:
        print(f"the template's history is in {root / HISTORY_DIR} (read it with `git --git-dir={HISTORY_DIR} log`); "
              "delete it when you no longer want it")
    elif mode == KEEP:
        print("this repository's own history is kept; the first commit is on top of it")
    print(f"open a session in {root}")
    return 0
