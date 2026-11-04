- This folder is a brain (`brain.json`); its skills are in `.claude/skills/`. **Call skills, never
  read them**: `references/` only load when the skill runs.
- Talk in the person's terms. If they do not speak git or terminal, say what a step does in plain
  words, not the command's output, and never ask them to run a command or edit a file you can do
  yourself. A secret's value is the exception: `_meta/brain env-sync --open` opens `.env` for them
  to fill in; never ask for a value in the chat.
- Work enters through the routing map (`docs/ROUTING.md`): start at its entry point, and when a
  skill says to hand on, call the next skill rather than doing its work inline. A router's choice
  comes from its rules; if the route looks wrong, fix the rule, never override it.
- A write blocked by the skill gate means: invoke the skill it names. Never route around the gate.
  A waiver needs the person's express say-so, every time.
- Terms mean what the glossary says: use its word, never one it lists under Avoid. A term that
  misled goes in it, through `brain-write-practice`. The glossary: @docs/GLOSSARY.md
- Before deciding a system cannot do something, read `docs/CAPABILITIES.md`.
- Before re-deriving a fact, search `docs/practices/` (`_meta/brain practices search <terms>`); for
  a `volatile` entry, run its `recheck` first.
- About to write a query or script you have written before: `brain-write-script`. Repeatable work
  no skill fits, or a skill that just went wrong: `brain-retro`.
- Project folders are not the brain. Never stage them into it; never edit another repo's files to
  fix the brain.
- Never edit `_meta/`, a `brain-*` skill or a managed block here. A change one of them needs goes
  to `brain-upstream`, which records it for the template.
- Skill, agent, script, practice and sync work in this brain goes through the `brain-*` skills,
  even when a globally installed skill (from another brain or a plugin) does a similar job: only
  the `brain-*` ones know this brain's conventions.
- Secrets live in `.env` (ignored), each a value or an `op://` 1Password reference. Never read,
  print or commit values. Names: `_meta/brain env-sync --list`; a new one: `env-sync --add KEY`,
  then `env-sync --open` for the person. Scripts take them through their loader; anything else
  gets them through `_meta/brain secret run KEY COMMAND`.
- An MCP server only this brain needs goes in its `.mcp.json`, through `brain-write-script`.
- A mod (a pane, band, command or hook inside Claude Code) lives in `.claude/mods/<prefix>-<name>/`
  and is written through `brain-write-mod`; edit it there, never through its link in `.claude/skills/`.
  A `mods/` folder of the person's own is theirs, never one of these.
- Work another brain handed over lands in `docs/INBOX.md`; the session-start check reports what is
  open. Offer to start on it, work it through the routing map, then set its status to `done` (or
  `declined: <reason>`) and commit. Brains this one knows (`brain.json` `brains`) are separate repos:
  read them, never edit them; hand work to one with `_meta/brain brains handoff`, or tell the person
  which brain to open and what to say there.
