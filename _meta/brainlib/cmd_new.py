"""`brain new`: make a brain from this template checkout (spec §6).

The command refuses before it builds anything: outside a template, on a bad prefix, on a folder that holds
something, on a pattern that cannot work. It then builds the whole brain (the shipped files and the filled
skeleton, the two `brain.json` files, the managed blocks and the manifest, `git init`, the pre-commit guard and
the first commit, which the guard reads) in a temporary folder next to the target, and moves it into place only
when the commit went through. Any failure removes the temporary folder and leaves the target as it was. The brain
is recorded in `local/brains.txt` last. `--dry-run` runs the same build in an OS temp folder, reports the files
and the guard's verdict, and discards it.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from . import config, gitutil, hook, install, managed, manifest, paths
from .report import BLOCK, WARN, Finding, emit

_EXPECTED = (install.InstallError, managed.ManagedError, hook.HookError, config.ConfigError, gitutil.GitError, OSError)
# Variables that point git at one particular repository. Set (a git hook exports them), they would send `git init`
# and the first commit to that repository instead of the new brain.
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
                      "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")


class _Failed(Exception):
    """The build stopped. `commit` is true when it was the first commit that git or the guard refused, and
    `detail` then holds what they said, a line each."""

    def __init__(self, what: str, commit: bool = False, detail: Optional[List[str]] = None) -> None:
        super().__init__(what)
        self.what = what
        self.commit = commit
        self.detail = detail or []


@dataclass
class _Plan:
    shipped: install.Files
    filled: install.Files
    raw: dict
    version: str
    message: str
    patterns: List[str]
    listed: List[str]


def add_arguments(parser) -> None:
    parser.add_argument("dir", metavar="DIR", help="the folder to make the brain in (new, or empty)")
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
                        help="build the brain in a temporary folder, report the files and whether the first "
                             "commit would go through, and write nothing in DIR")


def _refuse(message: str) -> int:
    print(f"new: {message}", file=sys.stderr)
    return 1


# -- what is checked before anything is built ---------------------------------------------------


def _folder_problem(dest: Path) -> Optional[str]:
    if os.path.lexists(str(dest)) and not dest.is_dir():
        return f"{dest} exists and is not a folder"
    if dest.is_dir() and any(dest.iterdir()):
        return f"{dest} is not empty; to turn an existing folder into a brain, use adopt"
    return None


def _hooks_path_problem() -> Optional[str]:
    """Git runs the guard from `<repo>/.git/hooks`, which it ignores while `core.hooksPath` is set. Ask from a
    scratch folder, where only the person's global and system settings (the ones a new repo inherits) apply."""
    with tempfile.TemporaryDirectory(prefix="brain-new-") as scratch:
        configured = str(gitutil.git(scratch, "config", "--get", "core.hooksPath", check=False)).strip()
    if configured:
        return (f"core.hooksPath is set ({configured}), so git would never run the brain's pre-commit guard; "
                "unset it, or call `_meta/brain hook pre-commit` from the hook that path holds, then run new again")
    return None


def _args_problem(args) -> Optional[str]:
    problem = config.validate_prefix(args.prefix)
    if problem:
        return problem
    for label, value in (("name", args.name), ("description", args.description)):
        if "\n" in value or "\r" in value:
            return f"the {label} must be one line"
    if not args.name.strip():
        return "the name must not be empty"
    for number, pattern in enumerate(args.private, 1):
        reason = install.private_pattern_problem(pattern)
        if reason:
            return f"--private: term {number} {reason}"
    clash = install.private_clash(args.private, [args.name, args.prefix, args.description])
    if clash:
        return (f"--private: term {clash} matches the brain's name, prefix or description, which its own files "
                "hold, so its first commit would be refused; change the name or drop the term")
    if not gitutil.has_identity():
        return gitutil.NO_IDENTITY
    return None


def _plan(args, template: Path) -> _Plan:
    """What to build, from the template's committed files."""
    files = install.template_files(template)
    shipped = install.shipped(files)
    starter = install.skeleton(files)
    if "_meta/brain" not in shipped or not starter:
        raise install.InstallError(f"{template} does not commit a harness and a skeleton (_meta/brain, "
                                   "_meta/skeleton/); is it the brain template?")
    version = install.version_string(template)
    name, description = args.name.strip(), args.description.strip()
    patterns = list(dict.fromkeys(p.strip() for p in args.private))
    values = {"name": name, "prefix": args.prefix, "description": description}
    filled = {rel: (install.fill(data, values), mode) for rel, (data, mode) in starter.items()}
    raw = install.new_brain_json(name, args.prefix, description, install.template_source(files), version,
                                 args.python, args.packages, bool(patterns))
    extra = ["brain.json", config.LOCAL_JSON, manifest.MANIFEST_PATH, "docs/practices/INDEX.md"]
    if patterns:
        extra.append(config.PRIVATE_FILE)
    return _Plan(shipped, filled, raw, version, f"meta(brain): initialise from template v{version}", patterns,
                 sorted(set(shipped) | set(filled) | set(extra)))


# -- building --------------------------------------------------------------------------------------


def _make(root: Path, plan: _Plan, template: Path) -> Tuple[str, List[str]]:
    """Build the brain in `root` (an empty folder), first commit included. Returns the commit's short sha and
    the warnings. Raises _Failed."""
    try:
        install.write_tree(root, plan.shipped, overwrite=False)
        install.write_tree(root, plan.filled, overwrite=False)
        config.write_raw(root, plan.raw)
        install.write_local(root, str(template))
        warnings = install.apply_managed(root)
        if plan.patterns:
            install.write_private(root, plan.patterns)
        manifest.write(root, sorted(plan.shipped))
        install.write_practices_index(root)
        install.git_init(root)
        hook.install(root)
    except _EXPECTED as exc:
        raise _Failed(str(exc)) from exc
    try:
        return install.first_commit(root, plan.message), warnings
    except gitutil.GitError as exc:
        lines = exc.stderr.strip().splitlines() or [str(exc)]
        raise _Failed("the first commit failed", commit=True, detail=lines) from exc
    except OSError as exc:
        raise _Failed("the first commit failed", commit=True, detail=[exc.strerror or str(exc)]) from exc


def _discard(folder: Path) -> None:
    """Remove a temporary folder this run made."""
    try:
        shutil.rmtree(str(folder))
    except FileNotFoundError:
        pass
    except OSError as exc:
        emit([Finding(WARN, "new", f"could not remove the temporary folder {folder} ({exc.strerror or exc}); "
                                   "delete it")])


def _create_parents(parent: Path) -> List[Path]:
    """Create `parent` and any missing folders above it; return the ones made, outermost first."""
    missing: List[Path] = []
    folder = parent
    while not folder.exists():
        missing.append(folder)
        folder = folder.parent
    made: List[Path] = []
    try:
        for folder in reversed(missing):
            folder.mkdir()
            made.append(folder)
    except OSError:
        _remove_folders(made)
        raise
    return made


def _remove_folders(made: List[Path]) -> None:
    """Take back the folders `_create_parents` made, innermost first, while they are empty."""
    for folder in reversed(made):
        try:
            folder.rmdir()
        except OSError:
            pass


def _new_sibling(target: Path) -> Path:
    """A new folder beside `target` (same filesystem, mode from the umask), named `.<name>.brain-new-<random>`."""
    for _ in range(100):
        candidate = target.parent / f".{target.name}.brain-new-{os.urandom(4).hex()}"
        try:
            os.mkdir(str(candidate))
        except FileExistsError:
            continue
        return candidate
    raise OSError("cannot find a free name for a temporary folder")


def _move_into_place(build: Path, target: Path) -> None:
    """Put the finished brain at `target`. A target that does not exist gets the folder itself (one rename). An
    empty folder that exists is filled instead of replaced, so it stays the same folder (a shell may be standing
    in it) with the mode it had; the entries are renamed and, if one cannot be, those already moved go back."""
    if not os.path.lexists(str(target)):
        os.rename(str(build), str(target))
        return
    moved: List[str] = []
    try:
        for name in sorted(os.listdir(str(build))):
            if os.path.lexists(str(target / name)):  # something appeared since the folder was found empty
                raise OSError(f"{target / name} appeared while the brain was being built")
            os.rename(str(build / name), str(target / name))
            moved.append(name)
    except OSError:
        for name in reversed(moved):
            try:
                os.rename(str(target / name), str(build / name))
            except OSError:
                pass
        raise


# -- the two ways to run -------------------------------------------------------------------------------


def _dry_run(dest: Path, template: Path, plan: _Plan) -> int:
    try:
        scratch = Path(tempfile.mkdtemp(prefix="brain-new-dry-run-"))
    except OSError as exc:
        return _refuse(f"cannot make a temporary folder for the dry run: {exc.strerror or exc}")
    failure: Optional[_Failed] = None
    warnings: List[str] = []
    try:
        _sha, warnings = _make(scratch, plan, template)
    except _Failed as exc:
        failure = exc
    finally:
        _discard(scratch)
    print(f"dry run: new would make a brain in {dest} from template v{plan.version}; nothing is written there:")
    for rel in plan.listed:
        print(f"  {rel}")
    emit([Finding(WARN, "new", w) for w in warnings])
    if failure is None:
        print(f"first commit: would succeed ({plan.message})")
        return 0
    if failure.commit:
        print("first commit: would be refused:")
        for line in failure.detail:
            print(f"    {line}")
    else:
        print(f"the build would fail: {failure.what}")
    return 1


def _doctor_summary(dest: Path) -> None:
    """What doctor finds in the new brain: the lines that block, if any, then its summary line (the warnings
    are one `_meta/brain doctor` away). The brain is made and stays made whatever doctor says, and a doctor that
    cannot run is only a warning."""
    from . import doctor

    try:
        found = doctor.diagnose(dest, quick=False)
    except Exception as exc:  # noqa: BLE001 - nothing doctor does may turn a finished new into a traceback
        emit([Finding(WARN, "new", f"doctor could not run ({type(exc).__name__}); run _meta/brain doctor in {dest}")])
        return
    emit([f for f in found if f.severity == BLOCK])
    print(doctor.summary(found))


def _real_run(dest: Path, template: Path, plan: _Plan) -> int:
    target = Path(os.path.realpath(str(dest)))  # a link to an empty folder is filled where it points
    created: List[Path] = []
    build: Optional[Path] = None
    placed = False
    failure: Optional[str] = None
    warnings: List[str] = []
    sha = ""
    try:
        created = _create_parents(target.parent)
        build = _new_sibling(target)
        sha, warnings = _make(build, plan, template)
        _move_into_place(build, target)
        placed = True
    except _Failed as exc:
        failure = exc.what + "".join("\n  " + line for line in exc.detail)
    except OSError as exc:
        failure = f"cannot make the brain in {dest}: {exc.strerror or exc}"
    finally:
        if not placed:
            if build is not None:
                _discard(build)
            _remove_folders(created)
        elif build is not None and build.exists():
            _discard(build)  # the entries moved out of it, so only the empty shell is left
    if failure is not None:
        return _refuse(f"{failure}\nnothing was written: {dest} is as it was")
    emit([Finding(WARN, "new", w) for w in warnings])
    try:
        install.register(template, dest)
    except OSError as exc:
        emit([Finding(WARN, "new", f"the brain was made, but could not be added to "
                                   f"{template / 'local' / 'brains.txt'}: {exc.strerror or exc}")])
    print(f"wrote {len(plan.listed)} files into {dest}")
    print(f"first commit {sha}: {plan.message}")
    _doctor_summary(dest)
    print(f"open a session in {dest}")
    return 0


def run(args) -> int:
    for name in _GIT_LOCATION_VARS:
        os.environ.pop(name, None)
    template = paths.harness_root()
    try:
        cfg = config.load(template)
    except config.ConfigError as exc:
        return _refuse(str(exc))
    if cfg.role != "template":
        return _refuse(f"run new from a template checkout; {template} is a brain (its brain.json does not "
                       'have "role": "template")')
    dest = Path(os.path.abspath(os.path.expanduser(args.dir)))  # a quoted ~ reaches here unexpanded
    try:
        problem = _args_problem(args) or _folder_problem(dest) or _hooks_path_problem()
        if problem:
            return _refuse(problem)
        plan = _plan(args, template)
    except _EXPECTED as exc:
        return _refuse(str(exc))
    if args.dry_run:
        return _dry_run(dest, template, plan)
    return _real_run(dest, template, plan)
