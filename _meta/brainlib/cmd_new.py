"""`brain new`: make a brain from this template checkout (spec §6).

The command refuses before it writes anything: outside a template, on a bad prefix, on a folder that holds
something, on a pattern that cannot work. After that it writes the shipped files and the filled skeleton, the
two `brain.json` files, the managed blocks and the manifest, then `git init`, the pre-commit guard and the first
commit, and last records the brain in `local/brains.txt`.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from . import config, gitutil, hook, install, managed, manifest, paths
from .report import WARN, Finding, emit

_EXPECTED = (install.InstallError, managed.ManagedError, hook.HookError, config.ConfigError, gitutil.GitError, OSError)
# Variables that point git at one particular repository. Set (a git hook exports them), they would send `git init`
# and the first commit to that repository instead of the new brain.
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
                      "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")


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
    parser.add_argument("--dry-run", action="store_true", help="list what would be written and write nothing")


def _refuse(message: str) -> int:
    print(f"new: {message}", file=sys.stderr)
    return 1


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
    for pattern in args.private:
        reason = install.private_pattern_problem(pattern)
        if reason:
            return f"--private: a pattern {reason}"
    return None


def _plan(args, template: Path, cfg: config.Config):
    """(shipped files, filled skeleton, brain.json, the version) from the template's committed files."""
    files = install.template_files(template)
    shipped = install.shipped(files)
    starter = install.skeleton(files)
    if "_meta/brain" not in shipped or not starter:
        raise install.InstallError(f"{template} does not commit a harness and a skeleton (_meta/brain, "
                                   "_meta/skeleton/); is it the brain template?")
    version = install.version_string(template)
    name, description = args.name.strip(), args.description.strip()
    values = {"name": name, "prefix": args.prefix, "description": description}
    filled = {rel: (install.fill(data, values), mode) for rel, (data, mode) in starter.items()}
    raw = install.new_brain_json(name, args.prefix, description, cfg.template_source, version, args.python,
                                 args.packages, bool(args.private))
    return shipped, filled, raw, version


def _paths_written(shipped, filled, private: bool) -> List[str]:
    extra = ["brain.json", config.LOCAL_JSON, manifest.MANIFEST_PATH, "docs/practices/INDEX.md"]
    if private:
        extra.append(config.PRIVATE_FILE)
    return sorted(set(shipped) | set(filled) | set(extra))


def _dry_run(dest: Path, template: Path, version: str, listed: List[str], message: str) -> int:
    print(f"dry run: nothing is written. new would make a brain in {dest} from template v{version}:")
    for rel in listed:
        print(f"  {rel}")
    print(f"then it would run git init, install the pre-commit guard, make the first commit ({message}) "
          f"and add {dest} to {template / 'local' / 'brains.txt'}")
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
    problem = _args_problem(args)
    dest = Path(os.path.abspath(args.dir))
    try:
        problem = problem or _folder_problem(dest)
        problem = problem or _hooks_path_problem()
        if problem:
            return _refuse(problem)
        shipped, filled, raw, version = _plan(args, template, cfg)
    except _EXPECTED as exc:
        return _refuse(str(exc))

    message = f"meta(brain): initialise from template v{version}"
    listed = _paths_written(shipped, filled, bool(args.private))
    if args.dry_run:
        return _dry_run(dest, template, version, listed, message)

    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _refuse(f"cannot create {dest}: {exc.strerror or exc}")
    try:
        install.write_tree(dest, shipped, overwrite=False)
        install.write_tree(dest, filled, overwrite=False)
        config.write_raw(dest, raw)
        install.write_local(dest, str(template))
        warnings = install.apply_managed(dest)
        if args.private:
            install.write_private(dest, args.private)
        manifest.write(dest, sorted(shipped))
        install.write_practices_index(dest)
        install.git_init(dest)
        hook.install(dest)
    except _EXPECTED as exc:
        return _stopped(dest, f"stopped before the first commit: {exc}")
    emit([Finding(WARN, "new", w) for w in warnings])
    try:
        sha = install.first_commit(dest, message)
    except gitutil.GitError as exc:
        detail = "\n".join("  " + line for line in exc.stderr.strip().splitlines()) or f"  {exc}"
        return _stopped(dest, f"the first commit failed:\n{detail}\nonce that is fixed, commit everything with "
                        f'the message "{message}" and add {dest} to local/brains.txt in the template')
    except OSError as exc:
        return _stopped(dest, f"the first commit failed: {exc.strerror or exc}")
    try:
        install.register(template, dest)
    except OSError as exc:
        print(f"WARN   new: could not add the brain to {template / 'local' / 'brains.txt'}: {exc.strerror or exc}")

    print(f"wrote {len(listed)} files into {dest}")
    print(f"first commit {sha}: {message}")
    print(f"open a session in {dest}")
    return 0


def _stopped(dest: Path, message: str) -> int:
    """Stop after the folder exists: what was written stays, so the person can read it and finish by hand."""
    print(f"new: {message}", file=sys.stderr)
    print(f"new: what was written is still in {dest}; fix the cause and finish by hand, or remove {dest} and "
          "run new again", file=sys.stderr)
    return 1
