"""`brain lint`: check every skill for broken references, gaps and orphans (spec §7.2)."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Set

from . import config, paths
from .config import Config
from .report import BROKEN, GAP, ORPHAN, Finding, emit, exit_code
from .skills import Skill, deep_skill_files, list_skills, named_skills, skill_prefixes, skills_dir

DESCRIPTION_LIMIT = 1024  # characters Claude Code accepts in a skill's description
BODY_LINE_LIMIT = 150  # lines after the frontmatter, past which a skill wants splitting

# Checks other modules add (routing map, router rules, gate rules). They run in `all_findings`,
# never in `lint_skills`, so this module's own checks can be counted exactly.
EXTRA_CHECKS: list[Callable[[Path, Config, List[Skill]], List[Finding]]] = []

# `references/x.md` or `scripts/a/b.py` that does not continue a longer path (`docs/references/x`).
_CITED = re.compile(r"(?<![\w/.-])(?:references|scripts)/[A-Za-z0-9_./-]+")
_PLACEHOLDER_NEXT = "<{[*$"  # `scripts/<system>/`, `references/*.md`: a pattern, not a path
_DOES_NOT = re.compile(r"\b[Dd]oes NOT\b")
_DONE_WHEN = re.compile(r"^##[ \t]+Done when\b", re.MULTILINE | re.IGNORECASE)


def cited_paths(text: str) -> List[str]:
    """The `references/…` and `scripts/…` paths `text` names, once each; placeholders are left out."""
    found: List[str] = []
    for match in _CITED.finditer(text):
        following = text[match.end():match.end() + 1]
        if following and following in _PLACEHOLDER_NEXT:
            continue
        cited = match.group().rstrip(".,)")
        if cited not in found:
            found.append(cited)
    return found


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:  # a name too long for the file system
        return False


def _is_cited(reference: str, cited: List[str]) -> bool:
    """True when `reference` is named, or sits under a named folder (never the bare `references/`)."""
    for path in cited:
        path = path.rstrip("/")
        if path == reference or (path != "references" and reference.startswith(path + "/")):
            return True
    return False


def _uncited_references(skill: Skill, cited: List[str]) -> List[str]:
    found = []
    base = skill.folder / "references"
    for dirpath, dirnames, filenames in os.walk(str(base)):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith("."):  # .DS_Store, .gitkeep
                continue
            relative = os.path.relpath(os.path.join(dirpath, filename), str(skill.folder))
            reference = Path(relative).as_posix()
            if not _is_cited(reference, cited):
                found.append(reference)
    return found


def _prefix_hint(cfg: Config, prefixes: Set[str]) -> str:
    wanted = sorted(prefixes) if cfg.role == "template" else [cfg.prefix or "<prefix>"]
    return " or ".join(f"'{p}-'" for p in wanted)


def _name_findings(skill: Skill, declared: Dict[str, List[str]]) -> List[Finding]:
    name = skill.meta.get("name", "").strip()
    if not name:
        return [Finding(BROKEN, skill.name, "frontmatter has no name")]
    if name == skill.name:
        return []
    others = [folder for folder in declared[name] if folder != skill.name]
    if others:
        return [Finding(BROKEN, skill.name, f"name '{name}' is also declared by {', '.join(others)}")]
    return [Finding(BROKEN, skill.name, f"name '{name}' does not match the folder name")]


def _description_findings(skill: Skill, known: Set[str], prefixes: Set[str]) -> List[Finding]:
    description = skill.meta.get("description", "").strip()
    if not description:
        return [Finding(BROKEN, skill.name, "frontmatter has no description")]
    found = []
    if len(description) > DESCRIPTION_LIMIT:
        found.append(Finding(BROKEN, skill.name,
                             f"description is {len(description)} characters (limit {DESCRIPTION_LIMIT})"))
    clause = _DOES_NOT.search(description)
    named = named_skills(description[clause.end():], prefixes) if clause else []
    if not named:
        found.append(Finding(GAP, skill.name, "description has no 'Does NOT' clause naming a sibling skill"))
    for ghost in (n for n in named if n not in known):
        found.append(Finding(BROKEN, skill.name, f"'Does NOT' clause names {ghost}, which does not exist"))
    return found


def _check_skill(skill: Skill, root: Path, cfg: Config, known: Set[str], prefixes: Set[str],
                 declared: Dict[str, List[str]]) -> List[Finding]:
    cited = cited_paths(skill.body)
    broken = _name_findings(skill, declared) + _description_findings(skill, known, prefixes)
    for path in cited:
        if not (_exists(skill.folder / path) or _exists(root / path)):
            broken.append(Finding(BROKEN, skill.name, f"cites {path}, which does not exist"))

    gaps = []
    if not any(skill.name.startswith(p + "-") for p in prefixes):
        gaps.append(Finding(GAP, skill.name, f"name does not start with {_prefix_hint(cfg, prefixes)}"))
    if not _DONE_WHEN.search(skill.body):
        gaps.append(Finding(GAP, skill.name, "no '## Done when' section"))
    lines = len(skill.body.splitlines())
    if lines > BODY_LINE_LIMIT:
        gaps.append(Finding(GAP, skill.name, f"body is {lines} lines (over {BODY_LINE_LIMIT})"))

    orphans = [Finding(ORPHAN, skill.name, f"{reference} is never cited in SKILL.md")
               for reference in _uncited_references(skill, cited)]
    return broken + gaps + orphans


def _check(root: Path, cfg: Config, skills: List[Skill]) -> List[Finding]:
    prefixes = skill_prefixes(cfg)
    known = {s.name for s in skills}
    declared: Dict[str, List[str]] = {}
    for skill in skills:
        name = skill.meta.get("name", "").strip()
        if name:
            declared.setdefault(name, []).append(skill.name)
    found: List[Finding] = []
    for skill in skills:
        found += _check_skill(skill, root, cfg, known, prefixes, declared)
    base = skills_dir(root)
    for path in deep_skill_files(root):
        relative = path.relative_to(base)
        message = f"{relative.as_posix()} is nested too deep to load; a skill is .claude/skills/<name>/SKILL.md"
        found.append(Finding(BROKEN, relative.parts[0], message))
    return found


def lint_skills(root: Path, cfg: Config) -> List[Finding]:
    """The skill checks of spec §7.2, without the extra checks other modules register."""
    return _check(Path(root), cfg, list_skills(root))


def all_findings(root: Path, cfg: Config) -> List[Finding]:
    """`lint_skills` plus every registered extra check (what `lint` prints and `doctor` reads)."""
    root = Path(root)
    skills = list_skills(root)
    found = _check(root, cfg, skills)
    for check in EXTRA_CHECKS:
        found += check(root, cfg, skills)
    return found


# -- the command ----------------------------------------------------------------------


def add_arguments(parser) -> None:
    """`lint` takes no arguments."""


def run(args) -> int:
    root = paths.harness_root()
    try:
        cfg = config.load(root)
    except config.ConfigError as exc:
        print(f"lint: {exc}", file=sys.stderr)
        return 1
    findings = all_findings(root, cfg)
    emit(findings)
    count = {sev: sum(1 for f in findings if f.severity == sev) for sev in (BROKEN, GAP, ORPHAN)}
    print(f"lint: {count[BROKEN]} broken, {count[GAP]} gap, {count[ORPHAN]} orphan")
    return exit_code(findings)
