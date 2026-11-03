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


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> Tuple[dict[str, str], str]:
    """Split `text` into its leading `---` frontmatter and the body that follows.

    Only single-line `key: value` pairs are read (a matching pair of quotes around the value is
    dropped; `[a, b]` stays a raw string); anything else in the block, such as an indented
    continuation or a comment, is skipped. Without a closed block the whole text is the body.
    """
    text = text[1:] if text.startswith("﻿") else text
    lines = text.split("\n")  # not splitlines(): a stray U+2028 in a value must not end the line
    if lines[0].rstrip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].rstrip() != "---":
            continue
        meta: dict[str, str] = {}
        for line in lines[1:end]:
            match = _KEY_VALUE.match(line.rstrip("\r"))
            if match:
                meta[match.group(1)] = _unquote(match.group(2))
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


def named_skills(text: str, prefixes: Set[str]) -> List[str]:
    """Tokens in `text` shaped `<prefix>-word(-word)*`, once each, in order of appearance.

    A token that is part of a path (`docs/lab-x`, `lab-x/SKILL.md`) or a file name (`lab-x.md`)
    is not a skill name.
    """
    if not prefixes:
        return []
    alternatives = "|".join(re.escape(p) for p in sorted(prefixes, key=len, reverse=True))
    pattern = re.compile(rf"(?<![\w./-])(?:{alternatives})(?:-[a-z0-9]+)+(?![\w/-]|\.\w)")
    found: List[str] = []
    for match in pattern.finditer(text):
        if match.group() not in found:
            found.append(match.group())
    return found


def owned_skills(cfg: Config, all_skills: List[Skill]) -> List[Skill]:
    """The skills this brain's `routing sync` writes: all but the template's `brain-*` in a brain, all in the template."""
    if cfg.role == "template":
        return list(all_skills)
    return [s for s in all_skills if not s.name.startswith("brain-")]
