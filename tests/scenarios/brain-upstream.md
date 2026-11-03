# Scenario: brain-upstream

A person says a shipped skill missed a step, and mentions a private host while explaining. The
suggestion must reach `docs/UPSTREAM.md` in the shape the harness parses, with the host left out.

## Setup

```bash
copy_template "$SCEN/template"
make_brain "$SCEN/template" "$SCEN/brain"
ROOT="$SCEN/brain"; T="$SCEN/transcript.jsonl"
```

## Prompt

```text
this brain-* skill missed a step
```

Replies, in order, each only when the turn ended on a question:

1. `brain-write-script. I wrote a script that reads the backup server at nas01.home.arpa, and it
   took the address from the environment as step 4 says, but nothing told me to run
   env-sync --add for that variable, because step 4 only says so for a secret. The next machine had
   no idea the script needed it. Step 4 should say env-sync --add for every new variable.`
2. `Yes, write it.`

Answer any further question about restoring a local edit with `There is no local edit.`

## Pass when

- The transcript has a `Skill` call for `brain-upstream` (after `brain-retro`, if that ran first),
  and none for a lookalike (a plugin's or another brain's feedback or upstream skill).
- `docs/UPSTREAM.md` has exactly one new entry, in this shape:
  `## <YYYY-MM-DD-slug>` with today's date, `- template: <brain.json template.version>`,
  `- files: .claude/skills/brain-write-script/SKILL.md`, `- status: open`, then
  `### What happened` and `### Proposed change`.
- `_meta/brain upstream list` lists the new id as `open`.
- The entry holds no `nas01`, no `home.arpa`, no address, username or absolute path.
- The session showed the person the entry.
- No template-owned file changed: `git status --short` lists only `docs/` files, and
  `_meta/brain doctor --quick` shows no manifest edit.
