- This folder is a brain (`brain.json`); its skills are in `.claude/skills/`. **Call skills, never
  read them**: `references/` only load when the skill runs.
- Work enters through the routing map (`docs/ROUTING.md`): start at its entry point, and when a
  skill says to hand on, call the next skill rather than doing its work inline. A router's choice
  comes from its rules; if the route looks wrong, fix the rule, never override it.
- A write blocked by the skill gate means: invoke the skill it names. Never route around the gate.
  A waiver needs the person's express say-so, every time.
- Before deciding a system cannot do something, read `docs/CAPABILITIES.md`.
- Before re-deriving a fact, search `docs/practices/` (`_meta/brain practices search <terms>`); for
  a `volatile` entry, run its `recheck` first.
- About to write a query or script you have written before: `brain-write-script`. Repeatable work
  no skill fits, or a skill that just went wrong: `brain-retro`.
- Project folders are not the brain. Never stage them into it; never edit another repo's files to
  fix the brain.
- Never edit `_meta/`, a `brain-*` skill or a managed block here. A change one of them needs goes
  to `brain-upstream`, which records it for the template.
- Skill, script, practice and sync work in this brain goes through the `brain-*` skills, even when
  a globally installed skill (from another brain or a plugin) does a similar job: only the
  `brain-*` ones know this brain's conventions.
- Secrets live in `.env` (ignored). Never read, print or commit values.
  Secret names: `_meta/brain env-sync --list`.
