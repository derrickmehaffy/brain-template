# Scenario: brain-write-skill

A person asks for a new skill in a brain that has none of its own yet.

## Setup

```bash
copy_template "$SCEN/template"
make_brain "$SCEN/template" "$SCEN/brain"
ROOT="$SCEN/brain"; T="$SCEN/transcript.jsonl"
```

## Prompt

```text
make a skill for checking my backups
```

Replies, in order, each only when the turn ended on a question:

1. `Two servers back up to the NAS every night. I want to know each morning whether last night's
   backup ran on both and whether one file restores from it. It only looks; it never changes a
   backup job. Put it where you think it belongs.`
2. `Yes, go ahead.`

## Pass when

- The transcript has a `Skill` call for `brain-write-skill`, and none for a skill-writing lookalike
  (a plugin's skill creator or skill-writing guide, another brain's `*-write-skill`).
- `.claude/skills/lab-<verb>-<object>/SKILL.md` exists for the backup check (for example
  `lab-check-backups`), with `name` equal to its folder.
- `docs/ROUTING.md` draws it, and an entry node reaches it: `_meta/brain routing show <skill>`
  shows an `(entry)` up its chain, and `lint` reports no "no entry node reaches" GAP.
- `_meta/brain lint` ends `lint: 0 broken, 0 gap, 0 orphan`.
- Its `SKILL.md` has `## Where this sits` with the generated `where:begin` … `where:end` block, and a
  `**Call it directly when:**` line under it that is not `TODO`.
- `_meta/brain routing sync --check` passes.
- Its description says what it does NOT do, naming a sibling, and its body has a `## Done when`.
