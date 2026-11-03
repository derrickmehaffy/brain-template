"""`brain adopt`: turn a folder that already holds work into a brain, without touching what is in it (spec §6).

It only adds files and inserts managed blocks: an existing file is kept, never moved, renamed, overwritten or
deleted, and the three files a brain edits in place (`CLAUDE.md`, `.gitignore`, `.claude/settings.json`) keep
every line they had. It refuses before writing anything when it could not keep that promise (a link or a file
where it would have to write a folder, a managed block that is broken, a git hook it must not replace).

The order is fixed: look at the folder and print what is there; write the missing brain files; set the managed
blocks and settings; `.env.example` from the key names in `.env`; `brain.json`, `brain.local.json`,
`.brain-private`; the manifest; `git init` if the folder is not a repository; the pre-commit guard; the entry in
`local/brains.txt`; then print what `git add -A` would stage. It never commits: `template-make-brain` goes through
that list with the person first.

`--dry-run` does all the looking and none of the writing, `git init` included. It reads repositories only through
`inventory`, which leaves their indexes alone.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from . import config, envsync, gitutil, hook, install, inventory, managed, manifest, paths
from .report import OK, WARN, Finding, emit

_EXPECTED = (install.InstallError, managed.ManagedError, hook.HookError, config.ConfigError, gitutil.GitError, OSError)
# Variables that point git at one particular repository. Set (a git hook exports them), they would send `git init`
# and the staging preview to that repository instead of the folder.
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
                      "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")

# Files adopt edits in place: a managed block or merged settings, around what the person wrote.
EDITED = ("CLAUDE.md", ".gitignore", install.SETTINGS)
_EDITED_NOTE = {
    "CLAUDE.md": "kept; the managed block goes above your text",
    ".gitignore": "kept; the managed block goes above your lines",
    install.SETTINGS: "kept; the .env deny entries and the gate hooks are merged in",
}
_EDITED_EMPTY = {"CLAUDE.md": b"", ".gitignore": b"", install.SETTINGS: b"{}\n"}
_MANAGED_BODIES = ("_meta/managed/CLAUDE.block.md", "_meta/managed/gitignore.block")
_ENV_EXAMPLE = ".env.example"
_PRACTICES_INDEX = "docs/practices/INDEX.md"
_OVER_LIMIT_SHOWN = 20
_LARGEST_SHOWN = 10

Files = install.Files


def add_arguments(parser) -> None:
    parser.add_argument("dir", metavar="DIR", help="the existing folder to turn into a brain")
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
                        help="print the inventory and the staging preview, and write nothing (not even git init)")


def _refuse(message: str) -> int:
    print(f"adopt: {message}", file=sys.stderr)
    return 1


# -- refusals, all before anything is written ---------------------------------------------------------


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


def _folder_problem(dest: Path, template: Path) -> Optional[str]:
    if not os.path.lexists(str(dest)):
        return f"{dest} does not exist; to start a brain in a new folder, use new"
    if not dest.is_dir():
        return f"{dest} is not a folder"
    if os.path.realpath(str(dest)) == os.path.realpath(str(template)):
        return f"{dest} is this template checkout; adopt turns another folder into a brain"
    if os.path.lexists(str(dest / config.BRAIN_JSON)):
        return f"{dest} is already a brain (it has {config.BRAIN_JSON}): run update there"
    return None


def _write_problem(dest: Path, to_write: List[str], edited: List[str]) -> Optional[str]:
    """Why a file in `to_write` cannot be created, or a file in `edited` changed, without writing through a link
    or replacing something that is not a plain file; None when all can."""
    for rel in sorted(to_write):
        walk = dest
        parts = rel.split("/")
        for index, part in enumerate(parts[:-1]):
            walk = walk / part
            shown = "/".join(parts[:index + 1])
            if os.path.islink(str(walk)):
                return (f"{shown} is a link, and adopt would write {rel} through it, outside this folder; "
                        "replace the link with a real folder (or move it aside) and run adopt again")
            if os.path.lexists(str(walk)) and not walk.is_dir():
                return f"{shown} is a file, so adopt cannot write {rel}; move it aside and run adopt again"
            if not os.path.lexists(str(walk)):
                break
    for rel in edited:
        if os.path.islink(str(dest / rel)):
            return (f"{rel} is a link, and adopt would replace it with a file; "
                    "make it a real file (or move it aside) and run adopt again")
    return None


def _hook_problem(dest: Path) -> Optional[str]:
    """Why the pre-commit guard could not be installed in `dest` (which is, or becomes, a repository)."""
    is_repo = gitutil.is_repo(dest)
    if is_repo:
        configured = str(gitutil.git(dest, "config", "--get", "core.hooksPath", check=False)).strip()
    else:  # a repository to be made inherits only the person's global and system settings: ask from a scratch folder
        with tempfile.TemporaryDirectory(prefix="brain-adopt-") as scratch:
            configured = str(gitutil.git(scratch, "config", "--get", "core.hooksPath", check=False)).strip()
    if configured:
        return (f"core.hooksPath is set ({configured}), so git would never run the brain's pre-commit guard; "
                "unset it, or call `_meta/brain hook pre-commit` from the hook that path holds, then run adopt again")
    if is_repo:
        common = str(gitutil.git(dest, "rev-parse", "--git-common-dir")).strip()
        target = (dest / common).resolve() / "hooks" / "pre-commit"
        if os.path.lexists(str(target)):
            try:
                same = target.read_bytes() == hook.SHIM.encode("utf-8")
            except OSError:
                same = False
            if not same:
                return (f"{target} is a pre-commit hook that is not the brain template's; move it aside and run "
                        "adopt again, or have it run `_meta/brain hook pre-commit` and install nothing here")
    return None


# -- the plan -------------------------------------------------------------------------------------------


def _example_from_env(dest: Path, starter: Files) -> Tuple[Optional[Tuple[bytes, int]], Optional[str]]:
    """(`.env.example` listing the key names `dest/.env` assigns, or None; a warning, or None). The skeleton's
    header comes first. Only names are read out of `.env`: no value reaches the new file or any message."""
    try:
        names = list(envsync.env_state(dest))
    except OSError as exc:
        return None, f"cannot read .env ({exc.strerror or exc}), so .env.example does not list its key names"
    if not names:
        return None, None
    header, mode = starter.get(_ENV_EXAMPLE, (b"# Secret NAMES only. Values go in .env, which is ignored.\n", 0o644))
    if header and not header.endswith(b"\n"):
        header += b"\n"
    return (header + b"".join(name.encode("ascii") + b"=\n" for name in names), mode), None


def _managed_preview(dest: Path, shipped: Files, starter: Files) -> Tuple[str, List[str]]:
    """(the `.gitignore` text adopt will leave, the warnings) from running the real `apply_managed` on a copy of
    the three files it edits, made in an OS temporary folder from what is in `dest` (or the skeleton's text for a
    file `dest` lacks). Raises ManagedError for a file adopt could not edit, before anything is written."""
    with tempfile.TemporaryDirectory(prefix="brain-adopt-") as scratch:
        base = Path(scratch)
        for rel in _MANAGED_BODIES:
            if rel in shipped:
                install.write_tree(base, {rel: shipped[rel]}, overwrite=True)
        for rel in EDITED:
            path = dest / rel
            try:
                data = path.read_bytes() if os.path.lexists(str(path)) else starter.get(
                    rel, (_EDITED_EMPTY[rel], 0o644))[0]
            except OSError as exc:
                raise managed.ManagedError(f"{rel}: cannot read it ({exc.strerror or exc})") from exc
            install.write_tree(base, {rel: (data, 0o644)}, overwrite=True)
        warnings = install.apply_managed(base)
        return (base / ".gitignore").read_text(encoding="utf-8"), warnings


def _settings_warning(text: str) -> Finding:
    """`apply_managed`'s warning about unparseable settings, in adopt's words (it cannot be run again)."""
    if text.startswith(install.SETTINGS + " is not valid JSON"):
        return Finding(WARN, install.SETTINGS, "is not valid JSON, so adopt left it as it is; the .env deny entries "
                       "and the skill gate hooks are not in it. Fix the file, then `_meta/brain update` adds them")
    return Finding(WARN, "adopt", text)


class _Plan:
    """Everything adopt will do, worked out from the folder and the template before anything is written."""

    def __init__(self, dest: Path, template: Path, args, cfg: config.Config) -> None:
        self.dest = dest
        files = install.template_files(template)
        self.shipped = install.shipped(files)
        starter = install.skeleton(files)
        if "_meta/brain" not in self.shipped or not starter:
            raise install.InstallError(f"{template} does not commit a harness and a skeleton (_meta/brain, "
                                       "_meta/skeleton/); is it the brain template?")
        self.version = install.version_string(template)
        name, description = args.name.strip(), args.description.strip()
        values = {"name": name, "prefix": args.prefix, "description": description}
        self.starter: Files = {rel: (install.fill(data, values), mode) for rel, (data, mode) in starter.items()}
        self.raw = install.new_brain_json(name, args.prefix, description, cfg.template_source, self.version,
                                          args.python, args.packages, bool(args.private))
        self.warnings: List[Finding] = []  # about .env, found while planning
        self.managed_findings: List[Finding] = []  # about the files that get a block or a merge
        self.private = list(args.private)

        if not os.path.lexists(str(dest / _ENV_EXAMPLE)):
            example, warning = _example_from_env(dest, self.starter)
            if example is not None:
                self.starter[_ENV_EXAMPLE] = example
            if warning:
                self.warnings.append(Finding(WARN, ".env", warning))

        self.files: Files = {**self.shipped, **self.starter}
        present = {rel for rel in self.files if os.path.lexists(str(dest / rel))}
        self.kept = sorted(present)
        self.fresh = sorted(set(self.files) - present)
        self.index_fresh = not os.path.lexists(str(dest / _PRACTICES_INDEX))
        self.generated = sorted({config.BRAIN_JSON, config.LOCAL_JSON, manifest.MANIFEST_PATH}
                                | ({_PRACTICES_INDEX} if self.index_fresh else set())
                                | ({config.PRIVATE_FILE} if self.private else set()))

    def problem(self) -> Optional[str]:
        edited = [*EDITED, config.LOCAL_JSON, *([config.PRIVATE_FILE] if self.private else [])]
        return _write_problem(self.dest, self.fresh + self.generated, edited) or _hook_problem(self.dest)

    def kept_findings(self) -> List[Finding]:
        found: List[Finding] = []
        for rel in self.kept:
            if rel in _EDITED_NOTE:
                found.append(Finding(OK, rel, _EDITED_NOTE[rel]))
            elif rel in self.shipped:
                same = _same_bytes(self.dest / rel, self.shipped[rel][0])
                found.append(Finding(OK if same else WARN, rel, "kept; it is the template's own file" if same else
                                     "kept, but it differs from the template's file of the same name; the "
                                     "manifest will list it as a local edit"))
            else:
                found.append(Finding(OK, rel, "kept; the skeleton's version is not written"))
        return found


def _same_bytes(path: Path, data: bytes) -> bool:
    try:
        return path.read_bytes() == data
    except OSError:
        return False


# -- the staging preview ----------------------------------------------------------------------------------


def _human(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = size / 1024
    for unit in ("KB", "MB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _is_env_file(rel: str) -> bool:
    base = rel.rsplit("/", 1)[-1]
    return base == ".env" or (base.startswith(".env.") and base != _ENV_EXAMPLE)


def _print_preview(dest: Path, listed: List[Tuple[str, int]], max_kb: int, was_repo: bool,
                   to_add: Optional[Tuple[int, int]] = None) -> None:
    """The staging preview. `to_add` is (files, bytes) of what adopt would still add, given in a dry run, where
    those files are not on disk yet and so are not in `listed`."""
    total = sum(size for _, size in listed)
    print(f"staging preview: what `git add -A` would stage in {dest}")
    print(f"  {len(listed)} file{'' if len(listed) == 1 else 's'}, {_human(total)}")
    if to_add is not None:
        print(f"  (the files that are here now; adopt would add about {to_add[0]} more, {_human(to_add[1])})")
    if was_repo:
        print("  (the folder is already a repository: files it tracks are listed too, and staging them changes "
              "nothing)")
    if listed:
        print("  largest:")
        for rel, size in sorted(listed, key=lambda item: (-item[1], item[0]))[:_LARGEST_SHOWN]:
            print(f"    {_human(size):>9}  {rel}")
    findings: List[Finding] = []
    over = sorted((item for item in listed if item[1] > max_kb * 1024), key=lambda item: (-item[1], item[0]))
    for rel, size in over[:_OVER_LIMIT_SHOWN]:
        findings.append(Finding(WARN, rel, f"{_human(size)} is over max_file_kb ({max_kb} KB), which the pre-commit "
                                "guard refuses; leave it out with a line in .gitignore below the managed block, or "
                                "list it in brain.json privacy.large_file_allow"))
    if len(over) > _OVER_LIMIT_SHOWN:
        findings.append(Finding(WARN, "adopt", f"and {len(over) - _OVER_LIMIT_SHOWN} more files over max_file_kb"))
    for rel, _ in listed:
        if _is_env_file(rel):
            findings.append(Finding(WARN, rel, "would be staged: an ignore rule of yours below the managed block "
                                    "lets it through, and the pre-commit guard refuses an env file; ignore it again"))
    emit(findings)


# -- the command ---------------------------------------------------------------------------------------------


def run(args) -> int:
    for name in _GIT_LOCATION_VARS:
        os.environ.pop(name, None)
    template = paths.harness_root()
    try:
        cfg = config.load(template)
    except config.ConfigError as exc:
        return _refuse(str(exc))
    if cfg.role != "template":
        return _refuse(f"run adopt from a template checkout; {template} is a brain (its brain.json does not "
                       'have "role": "template")')
    dest = Path(os.path.abspath(args.dir))
    try:
        problem = _args_problem(args) or _folder_problem(dest, template)
        if problem:
            return _refuse(problem)
        plan = _Plan(dest, template, args, cfg)
        problem = plan.problem()
        if problem:
            return _refuse(problem)
        gitignore_text, managed_warnings = _managed_preview(dest, plan.shipped, plan.starter)
    except _EXPECTED as exc:
        return _refuse(str(exc))
    plan.managed_findings = [_settings_warning(text) for text in managed_warnings]

    try:
        found = inventory.scan(dest)
    except _EXPECTED as exc:
        return _refuse(f"cannot look through {dest}: {exc}")
    max_kb = int(plan.raw["privacy"]["max_file_kb"])
    if args.dry_run:
        return _dry_run(dest, template, plan, found, gitignore_text, max_kb)

    print(f"adopting {dest} as a brain (template v{plan.version})")
    print(f"inventory of {dest}:")
    print(inventory.render(found))
    emit(plan.kept_findings())
    try:
        written = _write(dest, template, plan, args)
    except _EXPECTED as exc:
        return _stopped(dest, str(exc))
    emit([*plan.warnings, *plan.managed_findings])
    print(f"wrote {len(written)} files into {dest}")
    try:
        listed = inventory.staging_preview(dest, (dest / ".gitignore").read_text(encoding="utf-8"))
    except (*_EXPECTED, UnicodeDecodeError) as exc:
        print(f"WARN   adopt: could not work out what git add -A would stage ({exc})")
    else:
        _print_preview(dest, listed, max_kb, found.root_is_repo)
    print("no commit was made: go through the list above (template-make-brain does, with the person) before the "
          "first commit")
    return 0


def _write(dest: Path, template: Path, plan: _Plan, args) -> List[str]:
    """Every step that writes, in the pinned order; returns the paths written. Nothing existing is replaced except
    the three files whose managed parts are set in place."""
    written = install.write_tree(dest, plan.files, overwrite=False)
    config.write_raw(dest, plan.raw)
    written.append(config.BRAIN_JSON)
    install.write_local(dest, str(template))
    written.append(config.LOCAL_JSON)
    plan.managed_findings = [_settings_warning(text) for text in install.apply_managed(dest)]
    if plan.private:
        install.write_private(dest, plan.private)
        written.append(config.PRIVATE_FILE)
    ours = sorted(rel for rel in plan.shipped if rel in written or _same_bytes(dest / rel, plan.shipped[rel][0]))
    manifest.write(dest, ours)
    written.append(manifest.MANIFEST_PATH)
    if plan.index_fresh:
        install.write_practices_index(dest)
        written.append(_PRACTICES_INDEX)
    else:
        plan.warnings.append(Finding(WARN, _PRACTICES_INDEX, "kept; run `_meta/brain practices check` before the "
                                     "first commit, because the guard refuses an index that is not current"))
    if not gitutil.is_repo(dest):
        install.git_init(dest)
    hook.install(dest)
    try:
        install.register(template, dest)
    except OSError as exc:
        plan.warnings.append(Finding(WARN, "adopt", f"could not add the brain to {template / 'local' / 'brains.txt'}: "
                                     f"{exc.strerror or exc}"))
    return written


def _dry_run(dest: Path, template: Path, plan: _Plan, found: inventory.Inventory, gitignore_text: str,
             max_kb: int) -> int:
    print(f"dry run: nothing is written. adopt would turn {dest} into a brain (template v{plan.version}).")
    print(f"inventory of {dest}:")
    print(inventory.render(found))
    emit(plan.kept_findings())
    own = [rel for rel in plan.fresh if rel not in plan.shipped]
    harness = [rel for rel in plan.fresh if rel in plan.shipped]
    print(f"would write {len(plan.fresh) + len(plan.generated)} files, nothing over a file that is there:")
    for rel in sorted(own + plan.generated):
        print(f"  {rel}")
    print(f"  and {len(harness)} files of the template's harness (_meta/ and .claude/skills/brain-*/)")
    emit([*plan.warnings, *plan.managed_findings])
    print("it would also:")
    print("  add the managed block to CLAUDE.md and .gitignore (creating either if absent)")
    print("  merge the .env deny entries and the gate hooks into .claude/settings.json")
    if not found.root_is_repo:
        print("  run git init")
    print("  install the pre-commit guard")
    print(f"  add {dest} to {template / 'local' / 'brains.txt'}")
    print("and it would not commit.")
    try:
        listed = inventory.staging_preview(dest, gitignore_text)
    except _EXPECTED as exc:
        print(f"WARN   adopt: could not work out what git add -A would stage ({exc})")
        return 0
    added = (len(plan.fresh) + len(plan.generated), sum(len(plan.files[rel][0]) for rel in plan.fresh))
    _print_preview(dest, listed, max_kb, found.root_is_repo, to_add=added)
    return 0


def _stopped(dest: Path, message: str) -> int:
    """Stop after files were written: adopt only adds, so nothing of the person's has changed; say what to do."""
    print(f"adopt: stopped: {message}", file=sys.stderr)
    print(f"adopt: what was written stays in {dest} and nothing that was there has been changed; fix the cause and "
          "finish by hand (`_meta/brain hook install`, then add the folder to local/brains.txt in the template)",
          file=sys.stderr)
    return 1
