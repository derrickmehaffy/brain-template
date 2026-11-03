"""`brain adopt`: turn a folder that already holds work into a brain, without touching what is in it (spec §6).

It only adds files and inserts managed blocks: an existing file is kept, never moved, renamed, overwritten or
deleted, and the three files a brain edits in place (`CLAUDE.md`, `.gitignore`, `.claude/settings.json`) keep
every line they had. It refuses, before writing anything, when it could not keep that promise: a link or a file
where it would have to write a folder, a link where it would edit a file, a file it would write over, a managed
block that is already there or broken, a git hook it must not replace. The folder is looked through and its
inventory printed first, and then every such problem is listed as a `BLOCK` line, not only the first.

The order of the writes is fixed: the missing brain files; the managed blocks and settings; `.env.example` from
the key names in `.env`; `brain.json`, `brain.local.json`, `.brain-private`; the manifest; `git init` if the folder
is not a repository; the pre-commit guard; the entry in `local/brains.txt`; then it prints what `git add -A` would
stage. It never commits: `template-make-brain` goes through that list with the person first.

`--dry-run` does all the looking and none of the writing, `git init` included. It reads repositories only through
`inventory` and `gitutil`, which leave their indexes alone, and the scratch copies it makes live in the OS
temporary folder.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from . import config, envsync, gitutil, hook, install, inventory, managed, manifest, paths
from .report import BLOCK, OK, WARN, Finding, emit

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
# What starts the begin line of a managed block, per file (the same start `managed` looks for, so a block written
# under an older wording is seen too).
_BLOCK_STARTS = {"CLAUDE.md": "<!-- brain:begin", ".gitignore": "# <!-- brain:begin -->"}
_SHOWN = 20  # lines of one kind of finding before "and N more"
_LARGEST_SHOWN = 10
_LEFT_OUT_SHOWN = 12
_NEVER_LISTED = {".git", ".brain", config.PRIVATE_FILE, config.LOCAL_JSON, ".DS_Store"}  # never meant to be saved

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


def _link_problems(dest: Path, to_write: List[str], edited: List[str]) -> List[Finding]:
    """A `BLOCK` for each folder above a file adopt would create or edit that is a link (adopt would write outside
    the folder) or a file, and for each edited file that is itself a link (the edit would replace the link)."""
    found: List[Finding] = []
    seen = set()
    for rel in sorted(set(to_write) | set(edited)):
        walk = dest
        parts = rel.split("/")
        for index, part in enumerate(parts[:-1]):
            walk = walk / part
            shown = "/".join(parts[:index + 1])
            if os.path.islink(str(walk)):
                if shown not in seen:
                    found.append(Finding(BLOCK, shown, f"is a link, and adopt would write {rel} through it, outside "
                                         "this folder; replace the link with a real folder (or move it aside) and "
                                         "run adopt again"))
                seen.add(shown)
                break
            if os.path.lexists(str(walk)) and not walk.is_dir():
                if shown not in seen:
                    found.append(Finding(BLOCK, shown, f"is a file, so adopt cannot write {rel}; move it aside and "
                                         "run adopt again"))
                seen.add(shown)
                break
            if not os.path.lexists(str(walk)):
                break
    for rel in edited:
        if os.path.islink(str(dest / rel)) and rel not in seen:
            found.append(Finding(BLOCK, rel, "is a link, and adopt would replace it with a file; make it a real file "
                                 "(or move it aside) and run adopt again"))
    return found


def _existing_problems(dest: Path) -> List[Finding]:
    """A `BLOCK` for each file adopt writes whole that is already there (it would be written over)."""
    return [Finding(BLOCK, rel, "is already there, and adopt would write over it; move it aside and run adopt again")
            for rel in (config.LOCAL_JSON, manifest.MANIFEST_PATH) if os.path.lexists(str(dest / rel))]


def _hook_problems(dest: Path) -> List[Finding]:
    """A `BLOCK` when the pre-commit guard could not be installed in `dest`, which is, or becomes, a repository.

    A repository that does not exist yet is made as a trial in an OS temporary folder and looked at there, so
    whatever `git init` would give it (a hook from `init.templateDir` or `GIT_TEMPLATE_DIR`, `core.hooksPath` from
    the person's global settings) is found now and not after the files are written, when adopt could not be run
    again."""
    is_repo = gitutil.is_repo(dest)
    with tempfile.TemporaryDirectory(prefix="brain-adopt-") as scratch:
        repo = dest
        if not is_repo:
            repo = Path(scratch) / "trial"
            try:
                gitutil.git(scratch, "init", "-q", str(repo))
            except gitutil.GitError as exc:
                return [Finding(BLOCK, "git init", f"cannot make a repository to try the guard in: "
                                f"{(exc.stderr.strip().splitlines() or ['no message'])[0]}")]
        configured = str(gitutil.git(repo, "config", "--get", "core.hooksPath", check=False)).strip()
        if configured:
            return [Finding(BLOCK, "core.hooksPath", f"is set ({configured}), so git would never run the brain's "
                            "pre-commit guard; unset it, or call `_meta/brain hook pre-commit` from the hook that "
                            "path holds, then run adopt again")]
        common = str(gitutil.git(repo, "rev-parse", "--git-common-dir")).strip()
        target = (repo / common).resolve() / "hooks" / "pre-commit"
        if os.path.lexists(str(target)):
            try:
                same = target.read_bytes() == hook.SHIM.encode("utf-8")
            except OSError:
                same = False
            if not same:
                where = (str(target) if is_repo else "`git init` would put a pre-commit hook in the new repository "
                         "(from init.templateDir or GIT_TEMPLATE_DIR), and it")
                return [Finding(BLOCK, "pre-commit", f"{where} is not the brain template's hook; move it aside "
                                "(or have it run `_meta/brain hook pre-commit` and install nothing here) and run "
                                "adopt again")]
    return []


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


def _has_block(data: bytes, rel: str) -> bool:
    """Whether a text file already has a managed block (a begin line), complete or not, in any wording."""
    start = _BLOCK_STARTS.get(rel)
    return start is not None and any(line.startswith(start) for line in data.decode("utf-8", "replace").split("\n"))


def _managed_check(dest: Path, shipped: Files, starter: Files) -> Tuple[Optional[str], List[str], List[Finding]]:
    """(the `.gitignore` text adopt will leave or None, the warnings, a `BLOCK` per file adopt cannot edit).

    Each of the three files adopt edits is tried on its own with the real `apply_managed`, on copies in an OS
    temporary folder made from what is in `dest` (or the skeleton's text for a file `dest` lacks), so every file
    that cannot be edited is found, not just the first, and nothing is written in `dest`. A file that already has a
    managed block is refused too: setting the block would delete the text between its markers."""
    problems: List[Finding] = []
    warnings: List[str] = []
    gitignore_text: Optional[str] = None
    contents = {}
    for rel in EDITED:
        path = dest / rel
        try:
            contents[rel] = path.read_bytes() if os.path.lexists(str(path)) else starter.get(
                rel, (_EDITED_EMPTY[rel], 0o644))[0]
        except OSError as exc:
            problems.append(Finding(BLOCK, rel, f"cannot be read ({exc.strerror or exc})"))
    for rel in EDITED:
        if rel not in contents:
            continue
        with tempfile.TemporaryDirectory(prefix="brain-adopt-") as scratch:
            base = Path(scratch)
            for body in _MANAGED_BODIES:
                if body in shipped:
                    install.write_tree(base, {body: shipped[body]}, overwrite=True)
            for other in EDITED:
                data = contents[other] if other == rel else starter.get(other, (_EDITED_EMPTY[other], 0o644))[0]
                install.write_tree(base, {other: (data, 0o644)}, overwrite=True)
            try:
                found = install.apply_managed(base)
            except managed.ManagedError as exc:
                message = str(exc)
                problems.append(Finding(BLOCK, rel, message[len(rel) + 2:] if message.startswith(rel + ": ")
                                        else message))
                continue
            if _has_block(contents[rel], rel):
                problems.append(Finding(BLOCK, rel, "already has a managed block (from a brain, or copied from one); "
                                        "adopt keeps every line of a file it did not write and would replace the "
                                        "text between its markers, so remove the block and run adopt again"))
                continue
            if rel == ".gitignore":
                gitignore_text = (base / ".gitignore").read_text(encoding="utf-8")
            if rel == install.SETTINGS:
                warnings.extend(found)
    return gitignore_text, warnings, problems


def _settings_warning(text: str) -> Finding:
    """`apply_managed`'s warning about unparseable settings, in adopt's words (it cannot be run again)."""
    if text.startswith(install.SETTINGS + " is not valid JSON"):
        return Finding(WARN, install.SETTINGS, "is not valid JSON, so adopt left it as it is; the .env deny entries "
                       "and the skill gate hooks are not in it. Fix the file, then `_meta/brain update` adds them")
    return Finding(WARN, "adopt", text)


def _capped(findings: List[Finding], what: str) -> List[Finding]:
    """`findings` cut to `_SHOWN`, with one more line saying how many were left out."""
    if len(findings) <= _SHOWN:
        return findings
    return findings[:_SHOWN] + [Finding(WARN, "adopt", f"and {len(findings) - _SHOWN} more {what}")]


def _own_files(dest: Path, shipped: Files) -> List[Finding]:
    """The person's own files in the folders the template owns (`_meta/`, `.claude/skills/brain-*/`). They are kept,
    but `update` reads a file there that the manifest does not list as a local edit and stops until it is moved."""
    mine = [rel for rel in manifest.local_edits(dest) if rel not in shipped and os.path.lexists(str(dest / rel))]
    return _capped([Finding(WARN, rel, "is yours, in a folder the template owns; it is kept, but update lists it as a "
                            "local edit and stops until it is moved out") for rel in mine], "files of yours there")


def _unreadable(found: inventory.Inventory) -> List[Finding]:
    return _capped([Finding(WARN, rel, "cannot be read, so its size is not counted and a repository in it would not "
                            "be listed") for rel in found.unreadable], "folders that cannot be read")


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
        self.warnings: List[Finding] = []  # found while planning and checking; none of them stops the run
        self.managed_findings: List[Finding] = []  # about the files that get a block or a merge
        self.late: List[Finding] = []  # found while writing
        self.gitignore_text: Optional[str] = None  # the root .gitignore as adopt will leave it
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

    def check(self, found: inventory.Inventory) -> List[Finding]:
        """Every reason adopt cannot go on, as `BLOCK` findings (none: it can), found without writing anything in
        the folder. Also sets `gitignore_text`, `managed_findings`, and adds the warnings the inventory raises."""
        problems: List[Finding] = []
        try:
            edited = [*EDITED, config.LOCAL_JSON, *([config.PRIVATE_FILE] if self.private else [])]
            problems += _link_problems(self.dest, self.fresh + self.generated, edited)
            problems += _existing_problems(self.dest)
            problems += _hook_problems(self.dest)
            self.gitignore_text, managed_warnings, managed_problems = _managed_check(self.dest, self.shipped,
                                                                                      self.starter)
            problems += managed_problems
            self.managed_findings = [_settings_warning(text) for text in managed_warnings]
            self.warnings += _own_files(self.dest, self.shipped) + _unreadable(found)
        except _EXPECTED as exc:
            problems.append(Finding(BLOCK, "adopt", str(exc)))
        return problems

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


def _preview_findings(pv: inventory.Preview, max_kb: int) -> List[Finding]:
    found: List[Finding] = []
    over = sorted((item for item in pv.files if item[1] > max_kb * 1024), key=lambda item: (-item[1], item[0]))
    found += _capped([Finding(WARN, rel, f"{_human(size)} is over max_file_kb ({max_kb} KB), which the pre-commit "
                              "guard refuses; leave it out with a line in .gitignore below the managed block, or "
                              "list it in brain.json privacy.large_file_allow") for rel, size in over],
                     "files over max_file_kb")
    for folder, has_commit in pv.embedded:
        if has_commit:
            found.append(Finding(WARN, folder, "a repository the allowlist lets through; git add -A would stage it as "
                                 "an embedded repo, which the guard refuses; add "
                                 f"/{folder}/ below the managed block in .gitignore"))
        else:
            found.append(Finding(BLOCK, folder, "a repository with no commit, which the allowlist lets through; git "
                                 "add -A fails outright on it and stages nothing; add "
                                 f"/{folder}/ below the managed block in .gitignore"))
    tracked = set(pv.tracked)
    found += _capped([Finding(WARN, rel, "tracked by this repository although the managed block ignores it, and a "
                              "tracked file stays tracked whatever .gitignore says: git add -A stages any change to "
                              "it") for rel in pv.tracked if not _is_env_file(rel)], "tracked files the block ignores")
    for rel, _ in pv.files:
        if not _is_env_file(rel):
            continue
        if rel in tracked:
            found.append(Finding(BLOCK, rel, "tracked by this repository, so the managed block cannot hide it: git add "
                                 "-A stages any change to it, and the pre-commit guard refuses an env file; take it "
                                 "out of the index with git rm --cached. Its values are already in this folder's "
                                 "saved history, and reach any remote it is pushed to: change those secrets"))
        else:
            found.append(Finding(WARN, rel, "would be staged: an ignore rule of yours below the managed block lets it "
                                 "through, and the pre-commit guard refuses an env file; ignore it again"))
    return found


def _print_preview(dest: Path, pv: inventory.Preview, max_kb: int, was_repo: bool,
                   to_add: Optional[Tuple[int, int]] = None) -> None:
    """The staging preview. `to_add` is (files, bytes) of what adopt would still add, given in a dry run, where
    those files are not on disk yet and so are not in the list."""
    total = sum(size for _, size in pv.files)
    print(f"staging preview: what `git add -A` would stage in {dest}")
    print(f"  {len(pv.files)} file{'' if len(pv.files) == 1 else 's'}, {_human(total)}")
    if to_add is not None:
        print(f"  (the files that are here now; adopt would add about {to_add[0]} more, {_human(to_add[1])})")
    if was_repo:
        print("  (the folder is already a repository: the files it tracks are listed too, the ones the managed "
              "block ignores included; git add -A stages only what has changed)")
    if pv.files:
        print("  largest:")
        for rel, size in sorted(pv.files, key=lambda item: (-item[1], item[0]))[:_LARGEST_SHOWN]:
            print(f"    {_human(size):>9}  {rel}")
    left_out = _left_out(dest, pv)
    if left_out:
        shown = ", ".join(left_out[:_LEFT_OUT_SHOWN])
        more = f", and {len(left_out) - _LEFT_OUT_SHOWN} more" if len(left_out) > _LEFT_OUT_SHOWN else ""
        print(f"  not saved in the brain's history, so not backed up with it: {shown}{more}")
        print("  (to save one, add `!/<name>/` for a folder or `!/<name>` for a file below the managed block in "
              ".gitignore)")
    emit(_preview_findings(pv, max_kb))


def _left_out(dest: Path, pv: inventory.Preview) -> List[str]:
    """The top-level entries of `dest` the allowlist keeps out of the first commit (a folder with a trailing `/`),
    so the person knows what the brain does not save. Env files and this machine's own files are left unsaid."""
    staged = {rel.split("/", 1)[0] for rel, _ in pv.files}
    try:
        names = sorted(os.listdir(str(dest)))
    except OSError:
        return []
    return [name + ("/" if (dest / name).is_dir() else "") for name in names
            if name not in staged and name not in _NEVER_LISTED and not _is_env_file(name)]


def _show_preview(dest: Path, gitignore_text: Optional[str], found: inventory.Inventory, max_kb: int,
                  to_add: Optional[Tuple[int, int]] = None) -> None:
    if gitignore_text is None:
        print("staging preview: not available until the problems above are fixed (it needs the .gitignore adopt "
              "would write)")
        return
    try:
        pv = inventory.preview(dest, gitignore_text, found.root_is_repo)
    except (*_EXPECTED, UnicodeDecodeError) as exc:
        print(f"WARN   adopt: could not work out what git add -A would stage ({exc})")
        return
    _print_preview(dest, pv, max_kb, found.root_is_repo, to_add)


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
    dest = Path(os.path.abspath(os.path.expanduser(args.dir)))  # a quoted ~ reaches here unexpanded
    try:
        problem = _args_problem(args) or _folder_problem(dest, template)
        if problem:
            return _refuse(problem)
        plan = _Plan(dest, template, args, cfg)
        found = inventory.scan(dest)
    except _EXPECTED as exc:
        return _refuse(str(exc))
    max_kb = int(plan.raw["privacy"]["max_file_kb"])

    if args.dry_run:
        print(f"dry run: nothing is written. Looking at {dest} for template v{plan.version}.")
    else:
        print(f"adopting {dest} as a brain (template v{plan.version})")
    print(f"inventory of {dest}:")
    print(inventory.render(found))
    problems = plan.check(found)
    if args.dry_run:
        return _dry_run(dest, template, plan, found, problems, max_kb)
    if problems:
        emit([*plan.warnings, *problems])
        count = len(problems)
        print(f"adopt: refused: {count} problem{'' if count == 1 else 's'} above; nothing was written", file=sys.stderr)
        return 1

    emit([*plan.kept_findings(), *plan.warnings, *plan.managed_findings])
    try:
        written = _write(dest, template, plan)
    except _EXPECTED as exc:
        emit(plan.late)
        return _stopped(dest, str(exc))
    emit(plan.late)
    print(f"wrote {len(written)} files into {dest}")
    try:
        text = (dest / ".gitignore").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"WARN   adopt: could not read the .gitignore it wrote ({exc})")
    else:
        _show_preview(dest, text, found, max_kb)
    print("no commit was made: go through the list above (template-make-brain does, with the person) before the "
          "first commit")
    return 0


def _write(dest: Path, template: Path, plan: _Plan) -> List[str]:
    """Every step that writes, in the pinned order; returns the paths written. Nothing existing is replaced except
    the three files whose managed parts are set in place (`check` has already found that they can be)."""
    written = install.write_tree(dest, plan.files, overwrite=False)
    config.write_raw(dest, plan.raw)
    written.append(config.BRAIN_JSON)
    install.write_local(dest, str(template))
    written.append(config.LOCAL_JSON)
    install.apply_managed(dest)  # its warnings are the ones `check` already found, from the same files
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
        plan.late.append(Finding(WARN, _PRACTICES_INDEX, "kept; run `_meta/brain practices index` and stage it before "
                                 "the first commit, because the guard refuses an index that is not current"))
    if not gitutil.is_repo(dest):
        install.git_init(dest)
    hook.install(dest)
    try:
        install.register(template, dest)
    except OSError as exc:
        plan.late.append(Finding(WARN, "adopt", f"could not add the brain to {template / 'local' / 'brains.txt'}: "
                                 f"{exc.strerror or exc}"))
    return written


def _dry_run(dest: Path, template: Path, plan: _Plan, found: inventory.Inventory, problems: List[Finding],
             max_kb: int) -> int:
    if problems:
        emit([*plan.warnings, *problems])
    else:
        emit(plan.kept_findings())
        own = [rel for rel in plan.fresh if rel not in plan.shipped]
        harness = [rel for rel in plan.fresh if rel in plan.shipped]
        print(f"adopt would write {len(plan.fresh) + len(plan.generated)} files, nothing over a file that is there:")
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
    added = (len(plan.fresh) + len(plan.generated), sum(len(plan.files[rel][0]) for rel in plan.fresh))
    _show_preview(dest, plan.gitignore_text, found, max_kb, to_add=None if problems else added)
    if problems:
        count = len(problems)
        print(f"adopt: {count} problem{'' if count == 1 else 's'} above; nothing was written, and a real run would "
              "refuse", file=sys.stderr)
        return 1
    return 0


def _stopped(dest: Path, message: str) -> int:
    """Stop after files were written: adopt only adds, so nothing of the person's has changed; say what to do."""
    print(f"adopt: stopped: {message}", file=sys.stderr)
    print(f"adopt: what was written stays in {dest} and nothing that was there has been changed; fix the cause and "
          "finish by hand (`_meta/brain hook install`, then add the folder to local/brains.txt in the template)",
          file=sys.stderr)
    return 1
