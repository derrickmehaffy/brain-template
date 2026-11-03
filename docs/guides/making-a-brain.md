# Making a brain

How to decide what a brain is for, set it up, and let it grow. The commands are in the
[README](../../README.md); this is the judgement around them. For things to say to Claude at each
step, see [prompts.md](prompts.md).

## One brain per kind of work

A brain is for work you do again and again with Claude: a homelab, a game you mod, the open-source
projects you maintain, a team's support desk. It holds how to do that work well (skills, the facts
learned, what each system can and cannot do, small scripts), and the projects sit inside its folder
without being part of its git history.

Make one when you keep re-explaining the same context, the same mistakes come back, or the work
keeps touching the same few systems. Do not make one for a single task, or for a project that is
really part of work an existing brain already covers: give that brain a skill instead.

## Decide before setup

- **The folder.** Where you would start sessions for this work. Missing or empty: `new`. A folder you
  already work in, with project repos or data in it: `adopt`, which moves and overwrites nothing. A
  clone or copy of the template: `init`.
- **The prefix.** 2 to 16 lowercase letters or digits, starting with a letter. Every skill of the
  brain starts with it (`lab-check-backups`), so keep it short and unlike any other brain's.
- **Private terms.** Hostnames, addresses, unreleased names, client or customer names, written as
  you would say them. Setup keeps them in `.brain-private`, which git ignores, and the pre-commit
  guard refuses any commit that holds one. A family of names or an address range becomes one
  pattern, which Claude writes for you.
- **Where it is pushed.** A brain that holds infrastructure or customer detail goes to a private
  remote. The guard is the second line of defence, not the first.

## The first session

Open Claude Code at the brain's root: the skill gate, the `.env` deny and the brain's MCP servers
load only from there. The session starts with `doctor --brief`, which prints only what needs
attention; on a new brain that is usually "no online backup". Say "Back this brain up online", or
"Keep it on this computer only".

## Let it grow from real work

Do not write skills up front. A skill written from a guess routes badly and gets ignored; one written
from two real cases does not.

1. Work in the brain as you normally would. When work fits no skill, `brain-retro` records it in
   `docs/UNCLASSIFIED-LOG.md`.
2. The second time the same kind of work turns up, `brain-write-skill` turns the two cases into a
   skill and places it in the routing map (`docs/ROUTING.md`).
3. When you first use a system (an API, a CLI, an MCP server), `brain-write-script` probes it and
   records what it can and cannot do in `docs/CAPABILITIES.md`. A query you would write twice
   becomes a script.
4. A fact that took time to establish goes to `brain-write-practice`, with how sure it is
   (`researched`, `reproduced`, `reliable`) and the command that re-checks it.
5. A word that misled goes in `docs/GLOSSARY.md`, which every session loads.
6. When a skill gets something wrong, run `brain-retro` straight away: one row, one proposed fix.

Most brains have a handful of skills after a month. A brain for a busy, varied queue (a support
desk, say) can pass thirty, and then routers matter: when one entry point fans out to three or more
skills, `brain-write-skill` writes a router that picks by rule rather than by reading.

## Connecting systems

- **MCP servers.** A server only this brain needs goes in the brain's `.mcp.json`, through
  `brain-write-script`, not in your user settings. Servers in user settings load in every session
  you start anywhere, and their tool lists cost context in all of them, so move each one into the
  brain that uses it.
- **Secrets.** `.env` holds them, ignored by git and denied to Claude. Each value can be the secret
  itself or a 1Password reference (`op://vault/item/field`). Add a name with
  `_meta/brain env-sync --add KEY`; `env-sync --open` opens the file for you to paste the value. Scripts read secrets through their
  loader; anything else (an MCP server, a CLI) gets them through `_meta/brain secret run KEY COMMAND`.
- **What each system can't do** is the most useful line in `docs/CAPABILITIES.md`. A dated "cannot"
  stops the next session walking into the same wall.

## Keeping it healthy

- `brain-sync` commits with a scoped subject, and pushes only when you ask.
- Now and then, ask `brain-retro` which skills went unused (`_meta/brain usage`). A skill that never
  runs costs every session its description, so merge or remove it.
- `brain-setup` updates the brain from the template. A change every brain should have goes to
  `brain-upstream`, and `template-intake` takes it in on the template side.

## Several brains side by side

Each brain has its own skills, MCP servers and secrets, so start each session at the root of the
brain the work belongs to. Brains share only the `brain-*` skills that come from the template. A
domain skill two brains both want is copied, and each copy then changes on its own. To work in a
project nested inside a brain, still start the session at the brain's root: the project is inside
it, and a session started in the project misses the brain's safety checks.
