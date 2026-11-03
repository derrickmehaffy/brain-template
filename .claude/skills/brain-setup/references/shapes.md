# The four shapes of brain

A brain's shape is where its work lives and where chats start. Pick it from what the person described;
it can change later. The guides in `docs/guides/` (or online at the template's source) explain each
shape to the person; this file is what to do.

Three facts about Claude Code decide every layout here:

- A chat reads `.claude/settings.json` (the skill gate, the `.env` deny), its hooks and `.mcp.json`
  only from the folder it starts in. Start every chat at the brain's root.
- A chat loads `CLAUDE.md` from its folder **and every folder above it**. A project inside the brain
  gets the brain's `CLAUDE.md` too; a brain inside another brain gets both.
- `claude --add-dir <brain>` from elsewhere loads the brain's skills, but not its settings, hooks or
  MCP servers: the gate does not run there.

## Single project

One project worked on again and again: a marketing site, an app, a book, a home server's config.

```
<brain>/                      start every chat here
├─ <project>/                 the project's own repo, never saved in the brain
└─ .claude/skills/<prefix>-*  skills that name <project>/ paths
```

After `init`: clone the project in (`git clone <url> <project>`), or, for a folder they already
have, offer to move it in on a yes (never move it without one). If it must stay where it is, add its
folder to `.claude/settings.json` `permissions.additionalDirectories` and name the full path in
`CLAUDE.md`; its own `CLAUDE.md` then loads only when Claude works in its files. Write the
`CLAUDE.md` folder map line: `<project>/: <what it is>; its own repo, not part of the brain`.

## Multi-project

Several repos that belong together and share people, systems and words: a company's services, a
family of libraries, a client's sites.

```
<brain>/
├─ repos/<name>/              one folder per repo, each its own history
├─ work/                      the shared working folder: scratch, exports, per-task notes
└─ .claude/skills/<prefix>-*  skills that take a repo name, or work across all of them
```

`repos/` and `work/` are never saved in the brain: the allowlist `.gitignore` leaves them out. Clone
each repo into `repos/` on a yes; list each in the `CLAUDE.md` folder map with one line on what it
is. Skills take a repo name and write what they produce under `work/`, so no skill writes into a repo
it was not asked to change.

Skills available beyond this folder: a chat started inside `repos/<name>` loads the brain's
`CLAUDE.md` but not its gate or MCP servers. Say so, and recommend starting at the root. For a quick
question from inside a repo, `claude --add-dir <brain>` brings the skills; never copy them into
`~/.claude/skills`, where they would run in every chat without this brain's conventions.

## Massive

Many repos **and** several kinds of work, each its own chain of skills (releases, incidents,
customer questions, reporting), sharing systems and vocabulary.

Lay it out as multi-project, then:

- one entry node per kind of work in `docs/ROUTING.md`, in the person's words, and a router
  wherever an entry fans out to three or more skills (`brain-write-skill` writes both);
- `work/<area>/` per kind of work, or `work/<date>-<task>/` per task;
- `docs/<area>/` for what each area keeps, each listed in `docs/README.md`;
- report-only agents for large reads (a log, a big repo), dispatched by the skill that needs them;
- one glossary and one `docs/CAPABILITIES.md` for the whole brain: shared words are why it is one.

When two areas share no systems, words or people, they are two brains: suggest a hub instead.

## Brain of brains (a hub)

Several brains, and one place to ask "where does this go?". The hub knows what each brain is for and
hands work over; it never does another brain's work itself (that brain's gate and settings do not
run here).

```
Brains/
├─ hub/        the hub: brain.json lists ../homelab and ../game-mod
├─ homelab/
└─ game-mod/
```

Put the hub **beside** the brains, never above them: every chat in a brain below would load the hub's
`CLAUDE.md`. After `init`, run `_meta/brain brains add ../<name>` for each brain (it checks each is
one), then hand to `brain-write-skill` for the hub's routing skill, `<prefix>-route-work`:

1. `_meta/brain brains list`, then each candidate's `README.md` (things to say) and the entry
   points of its `docs/ROUTING.md`;
2. pick the brain, and say why;
3. **defer** (the default): tell the person which brain to open and exactly what to say there;
4. **push**, when the person wants it queued: `_meta/brain brains handoff <name> --title "..."
   --body "..."` with everything already known. The other brain's next chat reports it.

Work that fits no brain is the hub's unclassified log: it may be the next brain to make.
