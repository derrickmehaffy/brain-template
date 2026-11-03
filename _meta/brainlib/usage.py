"""`brain usage [--days N]`: how often each skill ran in this brain, from the log the skill gate keeps.

The gate's `record` hook appends one line per skill run to `.brain/skill-usage.log` (ignored, so it stays on this
machine). This counts the runs in the window: first the skills in `.claude/skills/`, busiest first, then those that
never ran (candidates to merge or remove, through `brain-retro`), then skills run here from elsewhere (a plugin,
another brain). Runs before the log existed are not counted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from . import paths
from .gate import USAGE_LOG
from .skills import list_skills

DEFAULT_DAYS = 90


def read_log(root: Path, since: datetime) -> Dict[str, Tuple[int, str]]:
    """skill -> (runs, date of the latest run) over the runs at or after `since`. A line that does not parse is
    skipped."""
    counts: Dict[str, Tuple[int, str]] = {}
    try:
        text = (Path(root) / USAGE_LOG).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return counts
    for line in text.splitlines():
        stamp, _tab, skill = line.partition("\t")
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if not skill or when.tzinfo is None or when < since:
            continue
        runs, last = counts.get(skill, (0, ""))
        counts[skill] = (runs + 1, max(last, when.date().isoformat()))
    return counts


def report(root: Path, days: int) -> List[str]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    counts = read_log(root, since)
    here = [skill.name for skill in list_skills(root)]
    ran = sorted((name for name in here if name in counts), key=lambda name: (-counts[name][0], name))
    total = sum(runs for runs, _last in counts.values())
    if not total:
        return [f"usage: no skill runs logged in the last {days} days (the skill gate's record hook writes "
                f"{USAGE_LOG.as_posix()})"]
    lines = [f"usage: {total} skill runs in the last {days} days"]
    width = max(len(name) for name in ran) if ran else 0
    lines += [f"  {name:<{width}}  {counts[name][0]:>4}  last {counts[name][1]}" for name in ran]
    never = [name for name in here if name not in counts]
    if never:
        lines.append(f"never ran in {days} days: {', '.join(never)}")
    elsewhere = sorted(name for name in counts if name not in here)
    if elsewhere:
        lines.append("other skills run here: " + ", ".join(f"{name} x{counts[name][0]}" for name in elsewhere))
    return lines


def add_arguments(parser) -> None:
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"the window, in days (default {DEFAULT_DAYS})")


def run(args) -> int:
    if args.days < 1:
        print("usage: --days must be 1 or more")
        return 2
    print("\n".join(report(paths.harness_root(), args.days)))
    return 0
