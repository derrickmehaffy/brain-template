"""The steps the commands that make a brain from the template share (spec §6): read the template's committed
files, split them into the shipped set and the skeleton, write files without ever leaving one half-written, set
the managed blocks and settings, and make the first commit.

Nothing here prints. A step that cannot go on raises `InstallError` (or the `ManagedError` or `GitError` of the
module underneath); the command decides what to say.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config, gitutil, managed, manifest

Files = Dict[str, Tuple[bytes, int]]  # relative path -> (content, mode)

SKELETON_DIR = "_meta/skeleton/"
# Stored under other names so a skeleton file never acts on the template repo itself.
SKELETON_RENAMES = {
    "gitignore": ".gitignore",
    "env.example": ".env.example",
    "claude-settings.json": ".claude/settings.json",
    "mcp.json": ".mcp.json",
}
SETTINGS = ".claude/settings.json"
PRIVATE_HEADER = (
    "# Terms that must never be committed: one regular expression per line, matched without regard to case.\n"
    "# The pre-commit guard blocks a staged file whose name or content matches one. Git ignores this file.\n"
)

_PLACEHOLDER = re.compile(rb"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_WALK_SKIP_ANYWHERE = {".git", "__pycache__"}
_WALK_SKIP_AT_ROOT = {"local", ".worktrees", ".superpowers"}  # none of them is ever shipped


class InstallError(Exception):
    """A step of making a brain cannot go on; the message says why in a sentence."""


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or ["no message"])[0]


# -- the template's files ---------------------------------------------------------------------------


def _walk(root: Path) -> Files:
    found: Files = {}
    for dirpath, dirnames, filenames in os.walk(str(root)):
        at_root = Path(dirpath) == root
        dirnames[:] = sorted(d for d in dirnames
                             if d not in _WALK_SKIP_ANYWHERE and not (at_root and d in _WALK_SKIP_AT_ROOT))
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if os.path.islink(full):  # as in `git archive`, a link is not a file
                continue
            with open(full, "rb") as handle:
                data = handle.read()
            mode = 0o755 if os.stat(full).st_mode & 0o111 else 0o644
            found[os.path.relpath(full, str(root)).replace(os.sep, "/")] = (data, mode)
    return found


def template_files(template_root) -> Files:
    """Every file of the template as it is committed: `git archive HEAD` when the template is a repo (an
    edit nobody committed is not the template), else its working tree without `.git`, `local` and bytecode."""
    root = Path(template_root)
    if gitutil.is_repo(root):
        try:
            return gitutil.archive(root, "HEAD")
        except gitutil.GitError as exc:
            raise InstallError(f"cannot read the committed files of {root} (has it a commit?): "
                               f"{_first_line(exc.stderr)}") from exc
    return _walk(root)


def shipped(files: Files) -> Files:
    """The files of `files` the template owns in a brain: `_meta/**` and `.claude/skills/brain-*/**`."""
    return {rel: value for rel, value in files.items() if manifest.is_shipped(rel)}


def skeleton(files: Files) -> Files:
    """The starter files under `_meta/skeleton/`, by the path they take in a brain (dotfiles renamed back)."""
    found: Files = {}
    for rel, value in files.items():
        if rel.startswith(SKELETON_DIR):
            inner = rel[len(SKELETON_DIR):]
            found[SKELETON_RENAMES.get(inner, inner)] = value
    return found


def fill(data: bytes, values: Dict[str, str]) -> bytes:
    """`data` with each `{{key}}` that `values` names replaced by its value; any other `{{...}}` stays. One
    pass, so a value that itself contains `{{prefix}}` is not expanded again."""
    def replace(match) -> bytes:
        key = match.group(1).decode("ascii")
        return values[key].encode("utf-8") if key in values else match.group(0)

    return _PLACEHOLDER.sub(replace, data)


def template_source(files: Files) -> Optional[str]:
    """`template.source` of the template's own `brain.json` as committed (`files` holds the commit), or None
    when there is none: the template is not published yet. Raises InstallError on a `brain.json` that is not a
    JSON object."""
    entry = files.get(config.BRAIN_JSON)
    if entry is None:
        return None
    try:
        raw = json.loads(entry[0].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raw = None
    if not isinstance(raw, dict):
        raise InstallError(f"the template's committed {config.BRAIN_JSON} is not a JSON object")
    section = raw.get("template")
    source = section.get("source") if isinstance(section, dict) else None
    return source if isinstance(source, str) and source else None


def version_string(template_root) -> str:
    """`<VERSION>+<short sha>` for a template that is a repo (VERSION as committed, sha of HEAD), else the
    VERSION file alone."""
    root = Path(template_root)
    is_repo = gitutil.is_repo(root)
    sha = gitutil.short_sha(root) if is_repo else None
    text: Optional[str] = None
    if sha:
        try:
            text = str(gitutil.git(root, "show", "HEAD:_meta/VERSION"))
        except gitutil.GitError:
            text = None
    if text is None:
        try:
            text = (root / "_meta" / "VERSION").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise InstallError(f"cannot read the template's _meta/VERSION: {getattr(exc, 'strerror', None) or exc}")
    version = text.strip()
    if not version:
        raise InstallError("the template's _meta/VERSION is empty")
    return f"{version}+{sha}" if sha else version


# -- writing files --------------------------------------------------------------------------------


def _write_atomic(path: Path, data: bytes, mode: int) -> None:
    """Write `data` to `path` through a scratch file beside it and `os.replace`, so the file is never seen
    half-written and is replaced rather than written through (a link is not followed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".brain-new")
    try:
        with open(str(scratch), "wb") as handle:
            handle.write(data)
        os.chmod(str(scratch), mode)
        os.replace(str(scratch), str(path))
    finally:
        if os.path.lexists(str(scratch)):
            os.unlink(str(scratch))


def _target(dest: Path, rel: str) -> Path:
    parts = rel.split("/")
    if rel.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise InstallError(f"refusing to write {rel!r}: a path inside the template must stay inside the folder")
    return dest.joinpath(*parts)


def write_tree(dest, files: Files, overwrite: bool) -> List[str]:
    """Write `files` under `dest`, sorted by path, and return the paths written. A file that already exists is
    left alone unless `overwrite`. Each file goes through a scratch file and `os.replace` and keeps its mode."""
    dest = Path(dest)
    written: List[str] = []
    for rel in sorted(files):
        target = _target(dest, rel)
        if os.path.lexists(str(target)) and not overwrite:
            continue
        data, mode = files[rel]
        _write_atomic(target, data, mode)
        written.append(rel)
    return written


# -- the brain's own files ------------------------------------------------------------------------


def new_brain_json(name: str, prefix: str, description: str, source: Optional[str], version: str, python: str,
                   packages: str, private_expected: bool) -> dict:
    """The `brain.json` of a new brain (spec §4). `private_file_expected` is added only when the brain has a
    `.brain-private`, so a brain without one is not told its guard is weaker."""
    privacy: dict = {"deny_patterns": [], "max_file_kb": 1024, "large_file_allow": []}
    if private_expected:
        privacy["private_file_expected"] = True
    return {
        "name": name,
        "prefix": prefix,
        "description": description,
        "template": {"source": source, "version": version},
        "scripts": {"python": python, "packages": packages},
        "privacy": privacy,
        "practices": {"stale_after_days": 180},
        "gates": [],
        "gates_off": [],
    }


def write_local(dest, template_source: str) -> None:
    """Set `template.source` in `brain.local.json` (this machine's location of the template; git ignores the
    file). Other keys already in it are kept. A file that exists but cannot be read, is not UTF-8 or is not a
    JSON object (with `template` an object, if present) raises InstallError instead of being rewritten."""
    path = Path(dest) / config.LOCAL_JSON
    current: dict = {}
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        text = None
    except OSError as exc:
        raise InstallError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError:
        raise InstallError(f"{path} is not UTF-8 text; fix or remove it and run this again") from None
    if text is not None:
        try:
            loaded = json.loads(text)
        except ValueError:
            loaded = None
        section = loaded.get("template") if isinstance(loaded, dict) else None
        if not isinstance(loaded, dict) or not (section is None or isinstance(section, dict)):
            raise InstallError(f"{path} is not a JSON object with an object under \"template\"; fix or remove it "
                               "and run this again")
        current = loaded
    template = current.get("template") or {}
    current["template"] = {**template, "source": template_source}
    _write_atomic(path, (json.dumps(current, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), 0o644)


def private_pattern_problem(pattern: str) -> Optional[str]:
    """None when `pattern` can be a line of `.brain-private`, else why not. Surrounding whitespace is not part
    of a pattern (the loader strips each line), so it is the stripped pattern that is judged."""
    pattern = pattern.strip()
    if not pattern:
        return "is empty"
    if "\n" in pattern or "\r" in pattern:
        return "must be on one line"
    if pattern.startswith("#"):
        return "starts with '#', which makes the line a comment"
    try:
        re.compile(pattern)
    except re.error:
        return "is not a valid regular expression"
    return None


def write_private(dest, patterns: List[str]) -> None:
    """Add `patterns` (stripped, each once) to `<dest>/.brain-private`, one per line, after any line already
    there (mode 0600). A file that exists but cannot be read or is not UTF-8 raises InstallError."""
    path = Path(dest) / config.PRIVATE_FILE
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        text = ""
    except OSError as exc:
        raise InstallError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError:
        raise InstallError(f"{path} is not UTF-8 text; fix or remove it and run this again") from None
    present = {line.strip() for line in text.splitlines()}
    fresh = [p for p in dict.fromkeys(p.strip() for p in patterns) if p and p not in present]
    if not text:
        text = PRIVATE_HEADER
    elif not text.endswith("\n"):
        text += "\n"
    _write_atomic(path, (text + "".join(p + "\n" for p in fresh)).encode("utf-8"), 0o600)


def write_practices_index(dest) -> None:
    """Write `docs/practices/INDEX.md` as `practices index` would, so the first commit holds a current one."""
    from . import practices

    dest = Path(dest)
    text = practices.render_index(practices.load_entries(dest), config.load(dest), date.today())
    _write_atomic(practices.practices_dir(dest) / practices.INDEX_FILE, text.encode("utf-8"), 0o644)


# -- the managed blocks and settings ----------------------------------------------------------------


def _existing(path: Path, label: str) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise managed.ManagedError(f"{label}: cannot read it ({exc.strerror or exc})") from exc


def _mode_of(path: Path) -> int:
    try:
        return os.stat(str(path)).st_mode & 0o777
    except OSError:
        return 0o644


def apply_managed(dest) -> List[str]:
    """Set the managed block in `CLAUDE.md` and `.gitignore` (bodies from `<dest>/_meta/managed/`) and the
    deny entries and gate hooks in `.claude/settings.json`; a file that is absent is created. Text outside a
    block, line endings and every other setting are kept. All three are computed before any is written, so a
    refusal leaves the brain as it was.

    Returns warnings. A `settings.json` that is not valid JSON is left as it is and reported, so the person
    fixes it; one that is JSON of the wrong shape, or a text file with a broken block, raises ManagedError
    naming the file.
    """
    dest = Path(dest)
    pending: List[Tuple[Path, bytes]] = []
    warnings: List[str] = []

    for rel, kind in (("CLAUDE.md", "md"), (".gitignore", "gitignore")):
        path = dest / rel
        raw = _existing(path, rel)
        body = managed.block_body(dest / "_meta", kind)
        try:
            text = "" if raw is None else raw.decode("utf-8")
            updated = managed.upsert(text, kind, body)
        except UnicodeDecodeError:
            raise managed.ManagedError(f"{rel}: is not UTF-8 text") from None
        except managed.ManagedError as exc:
            raise managed.ManagedError(f"{rel}: {exc}") from exc
        if raw is None or updated.encode("utf-8") != raw:
            pending.append((path, updated.encode("utf-8")))

    path = dest / SETTINGS
    raw = _existing(path, SETTINGS)
    current: Optional[dict] = {}
    if raw is not None:
        try:
            current = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            current = None
            warnings.append(f"{SETTINGS} is not valid JSON, so it was left as it is and the .env deny entries "
                            "and the skill gate hooks are not in it; fix it and run the command again")
    if current is not None:
        merged = managed.merge_settings(current)  # ManagedError names the file already
        text = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
        if raw is None or text.encode("utf-8") != raw:
            pending.append((path, text.encode("utf-8")))

    for target, data in pending:
        _write_atomic(target, data, _mode_of(target))
    return warnings


# -- git ----------------------------------------------------------------------------------------------


def git_init(dest) -> None:
    """`git init` in `dest`."""
    gitutil.git(dest, "init", "-q")


def first_commit(dest, message: str) -> str:
    """Stage everything the brain's `.gitignore` lets through, commit it (the pre-commit guard runs), and
    return the short sha. A refusal by the guard or by git raises GitError carrying what was said."""
    gitutil.git(dest, "add", "-A")
    gitutil.git(dest, "commit", "-q", "-m", message)
    return gitutil.short_sha(dest) or ""


def register(template_root, dest) -> None:
    """Append `dest` (absolute) to the template's `local/brains.txt`, once; the file and `local/` are created
    when missing."""
    listing = Path(template_root) / "local" / "brains.txt"
    wanted = os.path.abspath(str(dest))
    try:
        text = listing.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        text = ""
    known = {os.path.realpath(line.strip()) for line in text.splitlines() if line.strip()}
    if os.path.realpath(wanted) in known:
        return
    listing.parent.mkdir(parents=True, exist_ok=True)
    with open(str(listing), "a", encoding="utf-8", newline="\n") as handle:
        if text and not text.endswith("\n"):
            handle.write("\n")
        handle.write(wanted + "\n")
