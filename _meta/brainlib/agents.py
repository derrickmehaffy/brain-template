"""The brain's own agents (`.claude/agents/<prefix>-*.md`), checked as part of `brain lint`.

An agent is a helper a skill dispatches, never an entry point, so it is not in the routing map: the skill that
dispatches it names it. Claude Code skips an agent file whose frontmatter it cannot use, silently, so the
checks are the ones that keep an agent loadable and bounded.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from .config import Config
from .report import BROKEN, GAP, ORPHAN, Finding
from .skills import Skill, parse_frontmatter

AGENTS_DIR = Path(".claude") / "agents"


def own_agents(root: Path, cfg: Config) -> List[Path]:
    """The agent files this brain owns: `.claude/agents/<prefix>-*.md`, sorted."""
    if not cfg.prefix:
        return []
    try:
        return sorted(Path(root, AGENTS_DIR).glob(f"{cfg.prefix}-*.md"))
    except OSError:
        return []


def lint_agents(root: Path, cfg: Config, skills: List[Skill]) -> List[Finding]:
    """BROKEN when an agent's frontmatter has no `description` or a `name` other than its file name; GAP when it
    lists no `tools` (it would get every tool, MCP ones included) or no `model`; ORPHAN when no skill names it."""
    bodies = [skill.body for skill in skills]
    found: List[Finding] = []
    for path in own_agents(root, cfg):
        subject = (AGENTS_DIR / path.name).as_posix()
        try:
            meta, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            found.append(Finding(BROKEN, subject, f"cannot be read ({type(exc).__name__})"))
            continue
        if meta.get("name", "").strip() != path.stem:
            found.append(Finding(BROKEN, subject, f"frontmatter name must be {path.stem}, the file's name"))
        if not meta.get("description", "").strip():
            found.append(Finding(BROKEN, subject, "has no description, so it is never chosen"))
        if not meta.get("tools", "").strip():
            found.append(Finding(GAP, subject, "lists no tools, so it gets every tool; name the ones it needs"))
        if not meta.get("model", "").strip():
            found.append(Finding(GAP, subject, "names no model, so it runs on the session's; name the cheapest that "
                                               "does the job"))
        if not any(path.stem in body for body in bodies):
            found.append(Finding(ORPHAN, subject, "no skill names it; the skill that dispatches it should"))
    return found
