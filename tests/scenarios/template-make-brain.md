# Scenario: template-make-brain

In the template's own checkout, a person asks for a new brain at a folder that does not exist yet.

## Setup

```bash
copy_template "$SCEN/template"
ROOT="$SCEN/template"; T="$SCEN/transcript.jsonl"
TARGET="$SCEN/homelab"
```

## Prompt

The words, with `$TARGET` written out as its full path:

```text
make a brain for my homelab at $TARGET
```

Replies, in order, each only when the turn ended on a question:

1. `Name: Homelab. Prefix: lab. Description: Running and fixing the home network, its servers and
   their backups. Never commit: nas01.`
2. `Yes, go ahead.`

## Pass when

- The transcript has a `Skill` call for `template-make-brain`, and none for a lookalike (another
  brain's or a plugin's project or workspace creator).
- The session asked the four questions (name, prefix, description, what must never be committed)
  before running `new`.
- `_meta/brain new "$TARGET" … --dry-run` ran and was shown; the real `new` (without `--dry-run`)
  ran only in the turn after `Yes, go ahead.`
- `$TARGET` is a brain: `brain.json` prefix `lab`; one commit, `meta(brain): initialise from
  template v…`; `.brain-private` holds `nas01`; `"$TARGET/_meta/brain" doctor` exits 0.
- `$SCEN/template/local/brains.txt` lists `$TARGET`.
- The session named the folder to open the next session in: the brain root.
