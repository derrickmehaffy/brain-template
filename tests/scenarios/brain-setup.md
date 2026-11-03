# Scenario: brain-setup

A person cloned the template to use as a brain and asks for it to be set up: the copy route, which
runs `init` after four questions and a dry run.

## Setup

```bash
copy_template "$SCEN/template" nolocal
git clone -q "$SCEN/template" "$SCEN/clone"
ROOT="$SCEN/clone"; T="$SCEN/transcript.jsonl"
```

The clone has the template's `brain.json` (`role` `template`) and no `local/`: a copy never set up.

## Prompt

```text
set this up
```

Replies, in order, each only when the turn ended on a question:

1. `Name: Homelab. Prefix: lab. Description: Running and fixing the home network, its servers and
   their backups. Never commit: nas01.`
2. `Yes, go ahead.`

## Pass when

- The transcript has a `Skill` call for `brain-setup`, and none for a lookalike (another brain's
  setup skill, a plugin's init or onboarding command).
- The four questions came before any `init` ran.
- `_meta/brain init … --dry-run` ran, and the session showed what it would do and stopped; the real
  `_meta/brain init …` (without `--dry-run`) ran only in the turn after `Yes, go ahead.`
- Afterwards `brain.json` has prefix `lab` and is no longer `role` `template`; the latest commit is
  `meta(brain): initialise from template v…`; `.brain-private` holds `nas01` and no tracked file
  does.
- `_meta/brain doctor`, run from the clone afterwards, exits 0.
- The session told the person to start a new session at the folder's root.
