"""Finding and reading skills: `.claude/skills/<name>/SKILL.md` and the names inside their text."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set, Tuple

from .config import Config

SKILLS_DIR = (".claude", "skills")
SKILL_FILE = "SKILL.md"


@dataclass
class Skill:
    """One skill. `name` is its folder name (what the harness calls it); the frontmatter's own
    `name`, which lint holds equal to the folder, stays in `meta`."""

    name: str
    folder: Path
    path: Path
    meta: dict[str, str]
    body: str


# -- frontmatter -------------------------------------------------------------------

_KEY_VALUE = re.compile(r"^([A-Za-z0-9_-]+)[ \t]*:[ \t]*(.*?)[ \t]*$")
# `>`, `>-`, `|`, `|+`, `>2-` ...: the header of a YAML block scalar, optionally followed by a comment.
_BLOCK_HEADER = re.compile(r"^(?P<style>[>|])(?P<marks>[+\-1-9]{0,2})[ \t]*(?:#.*)?$")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _fold(lines: List[str]) -> str:
    """Join lines with single spaces; a blank line (or each of several) becomes a newline."""
    folded, pending = "", 0
    for line in lines:
        if not line:
            pending += 1
        elif not folded:
            folded, pending = line, 0
        else:
            folded += ("\n" * pending if pending else " ") + line
            pending = 0
    return folded


def _indented_run(block: List[str], start: int) -> int:
    """The index just past the lines from `start` on that are blank or indented."""
    end = start
    while end < len(block) and (not block[end].strip() or block[end][0] in " \t"):
        end += 1
    return end


def _block_scalar(header: re.Match[str], lines: List[str]) -> str:
    """The value of a `>` (folded) or `|` (literal) block whose indented `lines` follow its header."""
    first = next((line for line in lines if line.strip()), None)
    if first is None:
        return ""
    indent = len(first) - len(first.lstrip(" \t"))
    content = [line[indent:] if line.strip() and len(line) - len(line.lstrip(" \t")) >= indent
               else line.strip() for line in lines]
    blank_tail = 0
    while content and not content[-1]:
        content.pop()
        blank_tail += 1
    text = _fold(content) if header.group("style") == ">" else "\n".join(content)
    marks = header.group("marks")
    if "-" in marks:  # strip: no final newline
        return text
    return text + "\n" + ("\n" * blank_tail if "+" in marks else "")  # clip: one; keep: all


def _closing_quote(text: str, quote: str) -> int:
    """The index of the quote that closes the scalar `text` opens at index 0, or -1."""
    i = 1
    while i < len(text):
        if quote == '"' and text[i] == "\\":
            i += 2
        elif text[i] == quote and quote == "'" and text[i + 1:i + 2] == "'":
            i += 2  # '' is an escaped quote inside single quotes
        elif text[i] == quote:
            return i
        else:
            i += 1
    return -1


def _quoted_value(value: str, block: List[str], start: int) -> Tuple[str, int]:
    """The value of a quoted scalar that may run on over the lines from `start`, and the next line to read.

    A value whose quote never closes (or has trailing text other than a comment) is kept raw
    and swallows no following line.
    """
    quote, text, end = value[0], value, start
    while True:
        close = _closing_quote(text, quote)
        if close >= 0:
            break
        if end >= len(block):
            return value, start
        text += "\n" + block[end]
        end += 1
    rest = text[close + 1:].strip()
    if rest and not rest.startswith("#"):
        return _unquote(value), start
    parts = text[1:close].split("\n")
    if len(parts) == 1:
        return parts[0], end
    return _fold([part.strip(" \t") for part in parts]), end  # whitespace around a line break is dropped


def parse_frontmatter(text: str) -> Tuple[dict[str, str], str]:
    """Split `text` into its leading `---` frontmatter and the body that follows.

    Reads `key: value` pairs. A value is plain text (kept raw, so `[a, b]` stays a string) whose
    indented continuation lines are folded in with spaces (a blank line becomes a newline), a
    quoted string that may continue onto the next lines until its closing quote, or a block
    scalar: `>` folds its indented lines into one with spaces, `|` keeps the newlines, `-`
    drops the final newline and `+` keeps trailing blank lines. Nothing else is read: nested
    mappings, lists and comments are skipped. Quoted strings are not unescaped. Without a
    closed block the whole text is the body.
    """
    text = text[1:] if text.startswith("﻿") else text
    lines = text.split("\n")  # not splitlines(): a stray U+2028 in a value must not end the line
    if lines[0].rstrip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].rstrip() != "---":
            continue
        block = [line.rstrip("\r") for line in lines[1:end]]
        meta: dict[str, str] = {}
        n = 0
        while n < len(block):
            match = _KEY_VALUE.match(block[n])
            n += 1
            if not match:
                continue
            key, value = match.groups()
            header = _BLOCK_HEADER.match(value)
            if header:
                run_end = _indented_run(block, n)
                meta[key] = _block_scalar(header, block[n:run_end])
                n = run_end
            elif value[:1] in ("'", '"'):
                meta[key], n = _quoted_value(value, block, n)
            else:
                run_end = _indented_run(block, n)
                more = [line.strip(" \t") for line in block[n:run_end]]
                first = next((line for line in more if line), "")
                if value or not (_KEY_VALUE.match(first) or first == "-" or first.startswith("- ")):
                    value = _fold([value] + more)  # a plain value runs on over its indented lines, as in YAML
                    n = run_end
                meta[key] = value
        return meta, "\n".join(lines[end + 1:])
    return {}, text


# -- listing -----------------------------------------------------------------------


def skills_dir(root: Path) -> Path:
    return Path(root).joinpath(*SKILLS_DIR)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""  # lint then reports the missing name and description


def list_skills(root: Path) -> List[Skill]:
    """Every folder in `.claude/skills/` that holds a `SKILL.md`, sorted by folder name."""
    base = skills_dir(root)
    try:
        folders = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return []
    found = []
    for folder in folders:
        path = folder / SKILL_FILE
        if path.is_file():
            meta, body = parse_frontmatter(_read(path))
            found.append(Skill(folder.name, folder, path, meta, body))
    return found


def deep_skill_files(root: Path) -> List[Path]:
    """Every `SKILL.md` nested deeper than `.claude/skills/<name>/`; nothing loads these."""
    base = skills_dir(root)
    found = []
    for dirpath, _dirnames, filenames in os.walk(str(base)):
        if SKILL_FILE not in filenames:
            continue
        path = Path(dirpath) / SKILL_FILE
        if len(path.relative_to(base).parts) > 2:
            found.append(path)
    return sorted(found)


# -- names inside text -------------------------------------------------------------


def skill_prefixes(cfg: Config) -> Set[str]:
    """The prefixes a skill name can carry here: `brain`, this brain's own and, in the template, `template`."""
    prefixes = {"brain"}
    if cfg.prefix:
        prefixes.add(cfg.prefix)
    if cfg.role == "template":
        prefixes.add("template")
    return prefixes


def _name_pattern(prefixes: Set[str]) -> str:
    alternatives = "|".join(re.escape(p) for p in sorted(prefixes, key=len, reverse=True))
    return rf"(?<![\w./-])(?:{alternatives})(?:-[a-z0-9]+)+(?![\w/-]|\.\w)"


def named_skills(text: str, prefixes: Set[str]) -> List[str]:
    """Tokens in `text` shaped `<prefix>-word(-word)*`, once each, in order of appearance.

    A token that is part of a path (`docs/lab-x`, `lab-x/SKILL.md`) or a file name (`lab-x.md`)
    is not a skill name. Nothing here says the token is a skill: `brain-wide` has the prefix too.
    """
    if not prefixes:
        return []
    found: List[str] = []
    for match in re.finditer(_name_pattern(prefixes), text):
        if match.group() not in found:
            found.append(match.group())
    return found


def introduced_skills(text: str, prefixes: Set[str]) -> List[str]:
    """The names `text` introduces with "which is" or "that is", alone or as a list ("which is lab-a or lab-b").

    This is how a "Does NOT ..., which is X" clause points at the skill that does the work; only
    names introduced so are claimed to be skills. The introducer is lowercase and exact, and a
    list may be joined by commas, "or", "and" or "nor".
    """
    if not prefixes:
        return []
    item = rf"`?{_name_pattern(prefixes)}`?"
    separator = r"(?:\s*,\s*(?:(?:or|and|nor)\s+)?|\s+(?:or|and|nor)\s+)"
    phrase = re.compile(rf"\b(?:which|that) is\s+{item}(?:{separator}{item})*")
    found: List[str] = []
    for match in phrase.finditer(text):
        for name in named_skills(match.group(), prefixes):
            if name not in found:
                found.append(name)
    return found


def owned_skills(cfg: Config, all_skills: List[Skill]) -> List[Skill]:
    """The skills this brain's `routing sync` writes: all but the template's `brain-*` in a brain, all in the template."""
    if cfg.role == "template":
        return list(all_skills)
    return [s for s in all_skills if not s.name.startswith("brain-")]
