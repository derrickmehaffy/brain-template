"""`brain update`: pull the template's committed changes into this brain (spec §6).

The source of truth is the template's committed history, never its working tree: a local source is read with
`git archive` at `--ref` (default: its default branch) and a URL is shallow-fetched into an OS temporary folder
that is removed afterwards. The command refuses before it writes anything when a template-owned file here was
edited or has uncommitted changes, works out the whole plan in memory, then writes it: changed and new template
files, removal of the ones the template dropped, the managed blocks and settings entries, `_meta/MANIFEST.sha256`
and `brain.json` `template.version`. It does not commit; `brain-sync` does.

Everything this module needs is imported at the top. The update replaces the harness's own files while it runs,
and a module first imported afterwards would be read from a half-updated folder.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import changelog, config, gitutil, install, managed, manifest, paths, upstream
from .report import WARN, Finding, emit

_EXPECTED = (install.InstallError, managed.ManagedError, config.ConfigError, gitutil.GitError, OSError)
# Variables that point git at one particular repository. Set (a git hook exports them), they would send every
# git call here to that repository instead of the folders this command means.
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
                      "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")
# A URL source: a scheme git can fetch, or the `user@host:path` form. Anything else (`ext::...`, an option) is a path.
_URL = re.compile(r"^(?:(?:https?|ssh|git|file)://.+|[A-Za-z0-9._][A-Za-z0-9._-]*@[A-Za-z0-9._-]+:.+)$")
_CREDENTIALS = re.compile(r"(?<=//)[^/\s]*@")  # `user:token@` in a URL, to the last `@`: a password may hold one
_MANAGED_FILES = ("CLAUDE.md", ".gitignore", install.SETTINGS)
_MANAGED_WHAT = {"CLAUDE.md": "managed block", ".gitignore": "managed block",
                 install.SETTINGS: "gate hooks and .env deny entries"}
_KEEP_DIRS = {"_meta", ".claude", ".claude/skills"}  # the roots of the template-owned paths are never pruned
_SHOWN_FILES = 20


def add_arguments(parser) -> None:
    parser.add_argument("--from", dest="source", metavar="PATH|URL",
                        help="the template to read: a checkout on this machine or a git URL "
                             "(default: template.source in brain.local.json, else brain.json)")
    parser.add_argument("--ref", metavar="REF",
                        help="the branch, tag or commit to read (default: the template's default branch)")
    parser.add_argument("--dry-run", action="store_true", help="show what would change and write nothing")


def _masked(text: str) -> str:
    """`text` without the credentials a URL in it may carry."""
    return _CREDENTIALS.sub("***@", text)


def _refuse(message: str) -> int:
    print(f"update: {_masked(message)}", file=sys.stderr)
    return 1


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or ["no message"])[0]


# -- the template's committed files -------------------------------------------------------------------


@dataclass
class Source:
    files: install.Files  # every committed file of the template, by path
    version: str  # <VERSION>+<short sha>


def _is_bare(path: Path) -> bool:
    return str(gitutil.git(path, "rev-parse", "--is-bare-repository", check=False)).strip() == "true"


def _read_folder(spec: str, ref: Optional[str]) -> Tuple[install.Files, Optional[str]]:
    src = Path(os.path.abspath(os.path.expanduser(spec)))
    if not src.is_dir():
        raise install.InstallError(f"the template source {spec} is neither a folder nor a git URL")
    if not (gitutil.is_repo(src) or _is_bare(src)):
        raise install.InstallError(f"{src} is not a git repository; update reads the template's committed history")
    chosen = ref or gitutil.default_branch(src)
    return gitutil.archive(src, chosen), gitutil.short_sha(src, chosen)


def _read_url(spec: str, ref: Optional[str]) -> Tuple[install.Files, Optional[str]]:
    with tempfile.TemporaryDirectory(prefix="brain-update-") as scratch:
        try:
            gitutil.git(scratch, "init", "-q")
            gitutil.git(scratch, "fetch", "-q", "--depth", "1", "--", spec, ref or "HEAD")
        except gitutil.GitError as exc:
            raise install.InstallError(f"cannot fetch {spec}: {_first_line(exc.stderr)}") from exc
        return gitutil.archive(scratch, "FETCH_HEAD"), gitutil.short_sha(scratch, "FETCH_HEAD")


def _read_source(spec: str, ref: Optional[str]) -> Source:
    files, sha = (_read_url if _URL.match(spec) else _read_folder)(spec, ref)
    if "_meta/brain" not in install.shipped(files):
        raise install.InstallError(f"{spec} does not commit a harness (_meta/brain); is it the brain template?")
    data = files.get("_meta/VERSION")
    version = data[0].decode("utf-8", errors="replace").strip() if data else ""
    if not version:
        raise install.InstallError(f"{spec} commits no _meta/VERSION; is it the brain template?")
    return Source(files, f"{version}+{sha}" if sha else version)


# -- what stands in the way ---------------------------------------------------------------------------


def _uncommitted(root: Path) -> List[str]:
    """The template-owned paths with a change git has not committed: modified, staged, deleted or untracked."""
    if not gitutil.is_repo(root):
        return []
    raw = gitutil.git(root, "status", "--porcelain", "-z", "--untracked-files=all", "--", "_meta", ".claude/skills",
                      binary=True)
    tokens = [t.decode("utf-8", errors="surrogateescape") for t in raw.split(b"\0")]  # type: ignore[union-attr]
    found = set()
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if len(entry) < 4:
            continue
        found.add(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:  # a rename or copy names its origin in the next field
            found.add(tokens[i] if i < len(tokens) else "")
            i += 1
    return sorted(path for path in found if manifest.is_shipped(path))


def _listed(title: str, items: List[str]) -> List[str]:
    lines = [f"  {title}:"] + [f"    {item}" for item in items[:_SHOWN_FILES]]
    if len(items) > _SHOWN_FILES:
        lines.append(f"    ... and {len(items) - _SHOWN_FILES} more")
    return lines


def _refuse_dirty(edits: List[str], uncommitted: List[str]) -> int:
    lines = ["a template-owned file here differs from what the template installed or has uncommitted changes, "
             "so nothing was written:"]
    if edits:
        lines += _listed("edited, missing or extra (not what _meta/MANIFEST.sha256 recorded)", edits)
    if uncommitted:
        lines += _listed("uncommitted", uncommitted)
    if edits:
        lines.append("A change one of these files needs goes to the template as a suggestion: the brain-upstream "
                     "skill records it in docs/UPSTREAM.md and restores the file. Then run update again.")
    if uncommitted:
        lines.append("Uncommitted changes under _meta/ or a brain-* skill are usually an earlier update: the "
                     "brain-sync skill commits it as meta(brain). Or restore the files with git. Then run update "
                     "again.")
    return _refuse("\n".join(lines))


# -- the plan -----------------------------------------------------------------------------------------


@dataclass
class Plan:
    old_version: Optional[str]
    version: str
    added: List[str] = field(default_factory=list)  # template-owned files the brain does not have
    changed: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    writes: install.Files = field(default_factory=dict)  # the added and changed template-owned files
    keep: List[str] = field(default_factory=list)  # every template-owned file the brain will have
    managed_writes: install.Files = field(default_factory=dict)  # CLAUDE.md, .gitignore, settings.json
    managed_added: List[str] = field(default_factory=list)
    managed_changed: List[str] = field(default_factory=list)
    brain_json: Optional[bytes] = None  # the new brain.json when template.version moves
    warnings: List[str] = field(default_factory=list)
    entries: List[changelog.Entry] = field(default_factory=list)  # changelog entries newer than the installed version
    answered: List[Tuple[str, str]] = field(default_factory=list)  # (open suggestion id, the template's answer)

    @property
    def shipped_changed(self) -> bool:
        return bool(self.added or self.changed or self.removed)

    @property
    def is_empty(self) -> bool:
        return not (self.shipped_changed or self.managed_writes or self.brain_json is not None)


def _mode(path: Path) -> int:
    try:
        return os.stat(str(path)).st_mode & 0o777
    except OSError:
        return 0o644


def _same(path: Path, data: bytes, mode: int) -> bool:
    """Whether `path` is a regular file holding `data` with the executable bit `mode` has."""
    try:
        info = os.stat(str(path))
        if not stat.S_ISREG(info.st_mode) or bool(info.st_mode & 0o111) != bool(mode & 0o111):
            return False
        return path.read_bytes() == data
    except OSError:
        return False


def _put(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _plan_managed(root: Path, shipped: install.Files) -> Tuple[install.Files, List[str], List[str], List[str]]:
    """(writes, added, changed, warnings) for the managed blocks and settings entries, worked out on a copy: the
    source's block texts and the brain's three files go into a temporary folder and `install.apply_managed` runs
    there, so its checks and its output are exactly what `new` and `adopt` use, and a malformed file refuses the
    update before the brain is touched."""
    with tempfile.TemporaryDirectory(prefix="brain-update-") as staging:
        stage = Path(staging)
        for rel, (data, _) in shipped.items():
            if rel.startswith("_meta/managed/"):
                _put(stage / rel, data)
        before: Dict[str, Optional[bytes]] = {}
        for rel in _MANAGED_FILES:
            try:
                before[rel] = (root / rel).read_bytes()
            except FileNotFoundError:
                before[rel] = None
            current = before[rel]
            if current is not None:
                _put(stage / rel, current)
        warnings = install.apply_managed(stage)
        writes: install.Files = {}
        added: List[str] = []
        changed: List[str] = []
        for rel in _MANAGED_FILES:
            try:
                after = (stage / rel).read_bytes()
            except FileNotFoundError:
                continue
            if after != before[rel]:
                (added if before[rel] is None else changed).append(rel)
                writes[rel] = (after, _mode(root / rel))
        return writes, added, changed, warnings


def _plan_brain_json(root: Path, cfg: config.Config, version: str) -> Optional[bytes]:
    if cfg.template_version == version:
        return None
    raw = config.read_raw(root)
    section = raw.get("template")
    if isinstance(section, dict):
        section["version"] = version
    else:
        raw["template"] = {"version": version}
    return (json.dumps(raw, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _plan(root: Path, cfg: config.Config, source: Source) -> Plan:
    shipped = install.shipped(source.files)
    plan = Plan(cfg.template_version, source.version, keep=sorted(shipped))
    recorded = {rel for rel in manifest.read(root) if manifest.is_shipped(rel)}
    for rel in plan.keep:
        data, mode = shipped[rel]
        if rel not in recorded:
            plan.added.append(rel)
        elif not _same(root / rel, data, mode):
            plan.changed.append(rel)
        else:
            continue
        plan.writes[rel] = (data, mode)
    plan.removed = sorted(recorded - set(shipped))

    plan.managed_writes, plan.managed_added, plan.managed_changed, plan.warnings = _plan_managed(root, shipped)
    plan.brain_json = _plan_brain_json(root, cfg, source.version)

    changes = source.files.get(changelog.CHANGELOG_PATH)
    text = changes[0].decode("utf-8", errors="replace") if changes else ""
    plan.entries = changelog.newer_than(text, cfg.template_version)
    replies = changelog.answers(changelog.entries(text))
    try:
        mine = (root / upstream.UPSTREAM_PATH).read_text(encoding="utf-8", errors="replace")
    except OSError:
        mine = ""
    for suggestion in upstream.open_ids(mine):
        if suggestion in replies:
            kind, detail = replies[suggestion]
            plan.answered.append((suggestion, f"landed {detail}" if kind == "landed" else f"declined: {detail}"))
    return plan


# -- writing the plan ---------------------------------------------------------------------------------


def _holds_shipped(root: Path, folder: Path) -> bool:
    for dirpath, _dirnames, filenames in os.walk(str(folder)):
        for name in filenames:
            if manifest.is_shipped(os.path.relpath(os.path.join(dirpath, name), str(root)).replace(os.sep, "/")):
                return True
    return False


def _remove(root: Path, removed: List[str]) -> None:
    """Delete the files the template dropped, then the folders that held only them (and bytecode, a Finder file)."""
    for rel in removed:
        try:
            os.unlink(str(root / rel))
        except FileNotFoundError:
            pass
    folders = set()
    for rel in removed:
        parts = rel.split("/")[:-1]
        folders.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    for rel in sorted(folders - _KEEP_DIRS, key=lambda f: f.count("/"), reverse=True):
        folder = root / rel
        if folder.is_dir() and not folder.is_symlink() and not _holds_shipped(root, folder):
            shutil.rmtree(str(folder))


def _blocking(plan: Plan) -> bool:
    """Whether a dropped file stands where a written one needs a folder, or a folder where a written file goes
    (a file that became a folder or the reverse): then the removals must come first."""
    written = set(plan.writes)
    folders = {"/".join(w.split("/")[:i]) for w in written for i in range(1, w.count("/") + 1)}
    for rel in plan.removed:
        parts = rel.split("/")
        if rel in folders or any("/".join(parts[:i]) in written for i in range(1, len(parts))):
            return True
    return False


def _apply(root: Path, plan: Plan) -> None:
    removals_first = _blocking(plan)
    if removals_first:
        _remove(root, plan.removed)
    install.write_tree(root, plan.writes, overwrite=True)
    if not removals_first:
        _remove(root, plan.removed)
    install.write_tree(root, plan.managed_writes, overwrite=True)
    if plan.shipped_changed:
        manifest.write(root, plan.keep)
    if plan.brain_json is not None:
        brain_json = root / config.BRAIN_JSON
        install.write_tree(root, {config.BRAIN_JSON: (plan.brain_json, _mode(brain_json))}, overwrite=True)


# -- the report ---------------------------------------------------------------------------------------


def _skeleton_changes(plan: Plan) -> List[Tuple[str, str, str]]:
    """(verb, the path the starter file takes in a brain, its path under _meta/skeleton/) for each change."""
    found = []
    for verb, rels in (("added", plan.added), ("changed", plan.changed), ("removed", plan.removed)):
        for rel in rels:
            if rel.startswith(install.SKELETON_DIR):
                inner = rel[len(install.SKELETON_DIR):]
                found.append((verb, install.SKELETON_RENAMES.get(inner, inner), rel))
    return sorted(found, key=lambda item: item[1])


def _report(plan: Plan, dry_run: bool) -> None:
    old = plan.old_version or "unknown"
    counts = f"{len(plan.added)} added, {len(plan.changed)} changed, {len(plan.removed)} removed"
    if dry_run:
        print(f"dry run: nothing is written. update would bring this brain from template {old} to "
              f"{plan.version} ({counts}):")
    else:
        print(f"updated this brain from template {old} to {plan.version} ({counts}):")
    rows = [("added", rel) for rel in plan.added] + [("changed", rel) for rel in plan.changed]
    rows += [("removed", rel) for rel in plan.removed]
    rows += [("added", f"{rel} ({_MANAGED_WHAT[rel]})") for rel in plan.managed_added]
    rows += [("changed", f"{rel} ({_MANAGED_WHAT[rel]})") for rel in plan.managed_changed]
    if plan.brain_json is not None:
        rows.append(("changed", "brain.json (template.version)"))
    for verb, what in rows:
        print(f"  {verb:<7} {what}")

    skeleton = _skeleton_changes(plan)
    if skeleton:
        print(f"skeleton files changed since {old} (a brain keeps its own copy of these; merge the change by "
              "hand if you want it):")
        for verb, brain_path, rel in skeleton:
            print(f"  {verb:<7} {brain_path}  ({rel})")

    if plan.entries:
        count = len(plan.entries)
        since = old.split("+", 1)[0]
        print(f"changelog: {count} {'entry' if count == 1 else 'entries'} newer than {since}:")
        for version, body in plan.entries:
            print(f"## {version}")
            if body:
                print(body)
            print()
    if plan.answered:
        print("open upstream suggestions the template has answered:")
        for suggestion, answer in plan.answered:
            print(f"answered  {suggestion}  {answer}")
    if not dry_run:
        print(f'nothing is committed: brain-sync commits this as "meta(brain): update template to {plan.version}" '
              "and marks the answered suggestions in docs/UPSTREAM.md")


# -- the command --------------------------------------------------------------------------------------


def run(args) -> int:
    for name in _GIT_LOCATION_VARS:
        os.environ.pop(name, None)
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")  # a fetch that wants a password fails instead of waiting
    root = paths.harness_root()
    try:
        cfg = config.load(root)
        if cfg.role == "template":
            return _refuse(f"run update in a brain; {root} is the template (its brain.json has "
                           '"role": "template")')
        spec = args.source or config.effective_source(cfg)
        if not spec:
            return _refuse("no template source: pass --from")
        if args.ref is not None and (not args.ref or args.ref.startswith("-")):
            return _refuse("a ref must not be empty or start with '-'")
        source = _read_source(spec, args.ref)
        edits = manifest.local_edits(root)
        uncommitted = [path for path in _uncommitted(root) if path not in edits]
        if edits or uncommitted:
            return _refuse_dirty(edits, uncommitted)
        plan = _plan(root, cfg, source)
    except _EXPECTED as exc:
        return _refuse(str(exc))

    warnings = [Finding(WARN, "update", w) for w in plan.warnings]
    older = changelog.version_key(source.version)
    if plan.old_version and older and older < changelog.version_key(plan.old_version):
        warnings.append(Finding(WARN, "update", f"template {source.version} is older than the installed "
                                                f"{plan.old_version}"))
    emit(warnings)
    if plan.is_empty:
        print(f"already up to date: template {plan.version}")
        return 0
    if args.dry_run:
        _report(plan, dry_run=True)
        return 0
    try:
        _apply(root, plan)
    except _EXPECTED as exc:
        return _refuse(f"stopped part-way ({_masked(str(exc))}); template-owned files may be half-updated. Restore "
                       "them from git (git checkout -- _meta .claude/skills, and delete any new file under them), "
                       "fix the cause, and run update again")
    _report(plan, dry_run=False)
    return 0
