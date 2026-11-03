# The two logs

Both are Markdown tables in `docs/`, one row per occurrence, newest at the bottom. Keep each cell to
one line; a row someone has to scroll sideways through to understand is a row nobody reads. Never
put a `|` inside a cell (it splits the column); write "or" instead.

## `docs/RETRO-LOG.md`: a skill went wrong

```markdown
| Date | Skill | What went wrong | Fix | Status |
| --- | --- | --- | --- | --- |
```

- **Date**: the day it happened, `YYYY-MM-DD`.
- **Skill**: the skill that went wrong, or the one that should have run (for output written without
  its skill). For a routing failure, the router.
- **What went wrong**: the input in a few words, what the skill did, and what it should have done.
  Name the step it skipped when there was one: that is what the fix will target.
- **Fix**: the one change, with the file it lands in and the skill that makes it. `open` when the
  cause is not pinned yet.
- **Status**: `open`, `fixed YYYY-MM-DD`, `upstream <id>` (the `docs/UPSTREAM.md` entry now tracks
  it) or `declined: <reason>`. The Status is the only cell that changes after the row is written.

Example, from a homelab brain whose prefix is `lab`:

```markdown
| 2026-11-02 | lab-apply-firewall | Applied a rule change to the live router without the dry run; the person caught a wrong port only after it took effect | `lab-apply-firewall`: make "show the dry-run diff and wait for a yes" a must-obey step with its reason (brain-write-skill) | fixed 2026-11-02 |
```

A routing failure looks the same, with the router as the skill and the rule as the fix:

```markdown
| 2026-11-09 | lab-router | "Disk filling up on the backup box" went to lab-check-backups on Monday and lab-check-storage on Friday | `lab-router/rules.json`: rule `kind=disk` → lab-check-storage, with a case for this input (brain-write-skill) | open |
```

## `docs/UNCLASSIFIED-LOG.md`: work no skill fit

```markdown
| Date | The work | Closest skill | What a skill would need | Seen before |
| --- | --- | --- | --- | --- |
```

- **Date**: the day the work came in.
- **The work**: what was asked, in the person's words where possible, without project-specific names
  the guard would refuse.
- **Closest skill**: the skill it nearly fit, or `none`. When a router fell through to its default,
  the router.
- **What a skill would need**: the inputs it would take, the steps someone would otherwise
  reinvent, where its output goes, and any check before that output is trusted. This is the draft
  of the skill's body, so write it for whoever writes the skill.
- **Seen before**: `no`, or the date of the earlier row of the same kind. A date here means it is
  time to suggest `brain-write-skill`.

Example, from a game-modding brain whose prefix is `mod`:

```markdown
| 2026-11-02 | Convert a folder of exported textures to the game's format before a release build | mod-build-asset (models only) | the converter command per texture type, where converted files go (the project folder, not the brain), how to spot-check one in game | no |
```
