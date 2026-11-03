# Scenario: brain-retro

A shipped skill went wrong on real work: `brain-write-script` left a script loose in `scripts/`
instead of in a folder for the system it touches. `brain-write-script` is a `brain-*` skill, so the
fix is an upstream suggestion, not an edit here.

## Setup

```bash
copy_template "$SCEN/template"
make_brain "$SCEN/template" "$SCEN/brain"
ROOT="$SCEN/brain"; T="$SCEN/transcript.jsonl"

cat > "$ROOT/scripts/count_large_files.py" <<'PY'
"""WHY THIS EXISTS: how many files under a folder are over 1 GB, asked often enough to keep."""
from __future__ import annotations

import os
import sys


def count(top: str, limit: int = 1024 ** 3) -> int:
    return sum(
        1
        for folder, _dirs, files in os.walk(top)
        for name in files
        if os.path.getsize(os.path.join(folder, name)) > limit
    )


if __name__ == "__main__":
    print(count(sys.argv[1] if len(sys.argv) > 1 else "."))
PY
(cd "$ROOT" && git add scripts/count_large_files.py \
  && git commit -q -m "script(files): count files over 1 GB")
```

## Prompt

```text
brain-write-script put the script in the wrong folder
```

Replies, in order, each only when the turn ended on a question:

1. `It is scripts/count_large_files.py, from the last session. It went straight into scripts/
   instead of a folder for the system it touches; it only reads the file system.`
2. `Yes, send it upstream.`

## Pass when

- The transcript has a `Skill` call for `brain-retro`, and none for a retro lookalike (a plugin's
  or another brain's retrospective or lessons skill).
- `docs/RETRO-LOG.md` has one new row in the format of `brain-retro`'s `references/logs.md`: today's
  date, `brain-write-script` as the skill, what went wrong, one fix, and a Status.
- The fix it names is an upstream suggestion, since `brain-write-script` is a `brain-*` skill.
- After the yes, a `Skill` call for `brain-upstream` (the hand-off); the row's Status is
  `upstream <id>` once that entry is written, or `open`.
- Nothing under `_meta/` or `.claude/skills/brain-*/` changed (`git status --short`), and
  `brain.json` and the map are untouched.
