"""The template-owned blocks inside brain-owned files: the managed region of `CLAUDE.md` and `.gitignore`,
and the entries of `.claude/settings.json` that wire the skill gate and the session-start check (spec §4)."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MD_BEGIN = "<!-- brain:begin — managed by the brain template; edit below the end marker -->"
MD_END = "<!-- brain:end -->"
GI_BEGIN = "# <!-- brain:begin --> managed by the brain template; edit below the end marker"
GI_END = "# <!-- brain:end -->"

# kind -> (begin marker, the start every begin line has, end marker, file under `_meta/managed/`).
# A begin line is found by its start, so a block written under an older wording is still replaced.
_KINDS = {
    "md": (MD_BEGIN, "<!-- brain:begin", MD_END, "CLAUDE.block.md"),
    "gitignore": (GI_BEGIN, "# <!-- brain:begin -->", GI_END, "gitignore.block"),
}

DENY = ["Read(./.env)", "Read(./.env.*)"]
HOOK_CMD = '"$CLAUDE_PROJECT_DIR/_meta/brain" gate {}'  # quoted: the project folder may contain a space
START_CMD = '"$CLAUDE_PROJECT_DIR/_meta/brain" doctor --brief'
PRE_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|Bash"
POST_MATCHER = "Skill"
START_MATCHER = "startup"
# What every template hook command, now or in an older brain, contains: the gate's and the session-start check's.
_HOOK_MARKS = ('_meta/brain" gate', '_meta/brain" doctor')


class ManagedError(Exception):
    """A managed file or settings object the harness cannot safely edit."""


def _kind(kind: str) -> Tuple[str, str, str, str]:
    try:
        return _KINDS[kind]
    except KeyError:
        raise ManagedError(f"unknown managed kind '{kind}' (use one of {', '.join(_KINDS)})") from None


# -- blocks in text files ------------------------------------------------------------


def block_body(meta_dir: Path, kind: str) -> str:
    """The text between the markers for `kind`, from `<meta_dir>/managed/`, without a trailing newline."""
    name = _kind(kind)[3]
    path = Path(meta_dir) / "managed" / name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as why:
        raise ManagedError(f"cannot read {path} ({why.strerror or why})") from why
    return text.replace("\r\n", "\n").rstrip("\n")


def _find_block(text: str, begin_start: str, end: str) -> Optional[Tuple[int, int]]:
    """(start, stop) of the block: from the start of its begin line to the end of its end marker, so the
    text outside, line endings included, is never touched. None when there is no block."""
    span: Optional[Tuple[int, int]] = None
    start: Optional[int] = None
    position = 0
    for line in text.split("\n"):  # not splitlines(): only a line feed is a line break here
        marker = line.rstrip()
        if start is None:
            if line.startswith(begin_start):
                start = position
            elif marker == end:
                raise ManagedError("the end marker of the managed block has no begin marker before it")
        elif marker == end:
            if span is not None:
                raise ManagedError("the file holds more than one managed block")
            span, start = (start, position + len(marker)), None
        position += len(line) + 1
    if start is not None:
        raise ManagedError("the managed block has a begin marker but no end marker")
    return span


def upsert(text: str, kind: str, body: str) -> str:
    """`text` with its managed block set to `body`: replaced between the markers when the file has one, else
    inserted at the top followed by one blank line. Text outside the block is left as it was, and a file that
    uses CRLF gets a CRLF block. Raises `ManagedError` on a begin marker without an end (or the reverse)."""
    begin, begin_start, end, _ = _kind(kind)
    span = _find_block(text, begin_start, end)
    first = text.find("\n")
    newline = "\r\n" if first > 0 and text[first - 1] == "\r" else "\n"
    lines = body.replace("\r\n", "\n").rstrip("\n").split("\n") if body.strip("\n") else []
    block = newline.join([begin, *lines, end])
    if span is not None:
        return text[:span[0]] + block + text[span[1]:]
    rest = text.lstrip("\r\n")
    return block + newline + (newline + rest if rest else "")


# -- .claude/settings.json -----------------------------------------------------------


def _expect(value: Any, wanted: type, where: str) -> None:
    if not isinstance(value, wanted):
        raise ManagedError(f".claude/settings.json: {where} must be {'an object' if wanted is dict else 'a list'}")


def _is_template_hook(hook: Any) -> bool:
    command = hook.get("command") if isinstance(hook, dict) else None
    return isinstance(command, str) and any(mark in command for mark in _HOOK_MARKS)


def _without_template_hooks(groups: List[Any]) -> Tuple[List[Any], bool]:
    """`groups` (one event's matcher groups) with every template hook removed; a group left empty by that goes
    too. Also whether anything was removed."""
    kept: List[Any] = []
    removed = False
    for group in groups:
        inner = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(inner, list) or not any(_is_template_hook(hook) for hook in inner):
            kept.append(group)
            continue
        removed = True
        left = [hook for hook in inner if not _is_template_hook(hook)]
        if left:
            kept.append({**group, "hooks": left})
    return kept, removed


def _group(matcher: str, command: str) -> Dict[str, Any]:
    return {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}


def merge_settings(existing: Dict[str, Any]) -> Dict[str, Any]:
    """`existing` (the parsed `.claude/settings.json`) with the `.env` deny entries and the template hooks set:
    deny entries added once, every older template hook dropped, `PreToolUse` -> `gate check`,
    `PostToolUse` -> `gate record` and `SessionStart` -> `doctor --brief` added. Everything else is kept.
    Pure: `existing` is not modified."""
    _expect(existing, dict, "the file")
    result = copy.deepcopy(existing)

    permissions = result.setdefault("permissions", {})
    _expect(permissions, dict, "'permissions'")
    deny = permissions.setdefault("deny", [])
    _expect(deny, list, "'permissions.deny'")
    deny.extend(entry for entry in DENY if entry not in deny)

    hooks = result.setdefault("hooks", {})
    _expect(hooks, dict, "'hooks'")
    for event in list(hooks):
        _expect(hooks[event], list, f"'hooks.{event}'")
        kept, removed = _without_template_hooks(hooks[event])
        if not removed:
            continue
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    hooks.setdefault("PreToolUse", []).append(_group(PRE_MATCHER, HOOK_CMD.format("check")))
    hooks.setdefault("PostToolUse", []).append(_group(POST_MATCHER, HOOK_CMD.format("record")))
    hooks.setdefault("SessionStart", []).append(_group(START_MATCHER, START_CMD))
    return result
