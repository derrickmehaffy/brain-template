# Brain template (for sessions working on the template)

This folder is the template, not a brain: `brain.json` has `role: template` and prefix `template`.
`README.md` says what the template is; this file says how to work on it.

- **`brain-*` skills are the product.** They ship to every brain, and are edited here, directly,
  through `brain-write-skill`. This file has no managed block, and the template's
  `.claude/settings.json` wires the skill gate, so a write to a skill file is refused until
  `brain-write-skill` has run. Edit skills with `brain-write-skill`, scripts with `brain-write-script`.
- **`template-*` skills never ship.** `template-make-brain` and `template-intake` work on the
  template and stay in it. A new skill asks first: does it ship (`brain-*`) or stay (`template-*`)?
- **Shipped means copied into brains:** `_meta/**` and `.claude/skills/brain-*/**`, plus the managed
  blocks and the skeleton in `_meta/skeleton/`. Everything else here is template-only: this file,
  `README.md`, `brain.json`, `tests/`, `docs/`, `local/`. Skeleton files that are dotfiles or sit
  under `.claude/` are stored renamed (`gitignore`, `env.example`, `claude-settings.json`,
  `mcp.json`).
- **Run the test suite before committing:**
  `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . -v`. Then
  `_meta/brain doctor` (it needs `local/` and the pre-commit hook: `_meta/brain hook install`).
- **Nothing specific to where the template came from goes in a tracked file:** no organisation,
  product, system or person from the brains it was distilled from, and no absolute home path.
  `tests/test_origin.py` scans every tracked file against `local/origin-terms.txt` (ignored, so the
  terms are never written down in the repo). Write for any brain.
- **`local/` is never committed.** It holds notes, `origin-terms.txt` and `brains.txt` (the brains
  made from this checkout, one absolute path per line, which `template-intake` reads).
- **Brains get changes through `update`,** which reads the latest commit and not the working tree.
  A change brains should receive gets a `_meta/CHANGELOG.md` entry; one that answers an upstream
  suggestion cites its id (`- landed: <id> — <summary>` or `- declined: <id> — <reason>`).
- **Before publishing the template,** set `template.source` in `brain.json` to the published URL, so
  `init` in a clone of it starts a fresh history and never keeps the template as `origin`.
- **Commit through `brain-sync`.** Subjects are `meta(<area>)`, `skill(<name>)`, `docs(<area>)` or
  `test(<area>)`. Never push unless asked.
