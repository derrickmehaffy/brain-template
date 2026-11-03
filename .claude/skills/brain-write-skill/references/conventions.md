# Conventions for a skill in this brain

What a skill's files look like, what each check reports, and how a rename runs. The sequence and the
rules that must be obeyed are in `SKILL.md`; this file is the lookup.

## Folder layout

```text
.claude/skills/<prefix>-<verb>-<object>/
  SKILL.md        frontmatter and body: the only file that loads by itself
  references/     lookup material; every file here is cited from SKILL.md by its path
  scripts/        only when this skill is the sole caller (written through brain-write-script)
  rules.json      a router's rules (see routing.md, next to this file)
```

A skill is exactly `.claude/skills/<name>/SKILL.md`. One nested deeper never loads (lint: BROKEN).
Anything the skill produces for the work (drafts, configs, reports) goes where the body says, never
inside the skill folder.

## Frontmatter

```yaml
---
name: lab-check-backups
description: "Check that last night's backup jobs ran and can be restored from, and say which did not. Use when asked whether the backups are fine, after a host was rebuilt, or before a restore. Does NOT change a backup job, which is lab-change-config, and does NOT record why a job failed, which is brain-write-practice."
---
```

- Exactly two keys: `name` and `description`. `name` is the folder name, character for character.
- The description is one line of at most 1024 characters, in double quotes. Quote it because YAML
  ends an unquoted value at ` #` (the rest becomes a comment and silently disappears) and refuses
  `: ` inside one. Never put a `"` inside it; reword instead.
- Three parts, in this order:
  1. **What it does**, as a verb phrase, specific enough to tell it from its neighbours.
  2. **`Use when …`**, in the words a person would actually say, plus the moments other skills or
     the harness send work to it (a gate refusal, a failed check, a router's rule).
  3. **`Does NOT …, which is <sibling>`** for each skill it could be mistaken for. `which is` (or
     `that is`, also with a list: "which is lab-a or lab-b") tells `lint` the name is a skill, so a
     name that does not exist is BROKEN. A sibling named anywhere after "Does NOT" satisfies the
     GAP check, but only an introduced one is verified to exist.
- It is written for whoever chooses between skills: a router, another skill, an agent reading a
  hundred descriptions. Words a person would type beat a summary of the body.

## Names

`<prefix>-<verb>-<object>`, lowercase, words joined by `-`. The prefix is `prefix` in `brain.json`;
`brain-` belongs to the shipped skills and `template-` to the template. Reuse the verbs the brain
already has (`ls .claude/skills`), so its families stay visible in a listing:

| Verb | Means | Examples |
| --- | --- | --- |
| `check` | reads and reports; changes nothing | `lab-check-backups`, `plug-check-compat` |
| `change`, `apply` | changes a live system or a project repo | `lab-change-config`, `mod-apply-patch` |
| `write` | produces a document someone reads or publishes | `plug-write-changelog`, `mod-write-listing` |
| `triage` | classifies what came in and says what it is | `plug-triage-issue` |
| `router` | the entry point that names the next skill by rule | `lab-router`; a second one is `lab-route-<input>` |

The verb tells a reader, before opening the file, whether the skill changes anything. A name that
only makes sense after reading the description is the wrong name. Rename only with `rename-skill`.

## Body

```markdown
# <What it does, as a title>

<One or two lines: what it is for, and what makes doing it well not obvious.>

## Where this sits

**Call it directly when:** <the deliberate way in mid-flow, naming any earlier step that still applies>

## <The sequence, or the sections the work needs>

1. **<Step>.** <What to do, and why it matters>. Read `references/<file>` <for what>.

## Do not

- <A rule people actually break, with the reason>

## Done when

- <A condition someone can check: a file exists, a command passes, the person said yes>
```

- About 100 lines, the generated block included. `lint` reports a GAP past 150: time to split.
- Leave `## Where this sits` empty: `_meta/brain routing sync` writes the block under it, between
  `where:` markers. Write the call line by hand, below the block's end marker, as one sentence. Sync
  adds a `TODO` call line when there is none, and `lint` reports it until it is replaced.
- Every path the skill writes is named in the body, so the next agent does not put it wherever it is
  standing, and so a gate rule (gates.md) has a path to cover.
- `lint` reads every `references/…` or `scripts/…` token in `SKILL.md` as a path that must exist,
  relative to the skill folder, then to the brain root. Write a placeholder (`references/<file>`,
  `scripts/<system>/`) when you mean no particular file. Every file under `references/` must be
  cited, or it is an ORPHAN: nothing would ever tell an agent to read it.
- `## Done when` holds conditions someone else could check, not "the work is good".

A call line, for a skill that checks a config change before it is applied:

```markdown
**Call it directly when:** a config change is already written and only needs checking before it
is applied; if `lab-router` did not route it here, record its fields first.
```

## What lint reports

`_meta/brain lint` prints one line per finding, `SEVERITY subject: message`, then
`lint: N broken, N gap, N orphan`. It exits 1 when anything is BROKEN, else 0.

| Severity | Means | Findings |
| --- | --- | --- |
| BROKEN | loads wrongly, or routes wrongly; fails the run, and the commit | frontmatter without `name` or `description`; `name` not the folder name, or declared by two folders; a `SKILL.md` nested too deep; a description over 1024 characters; a cited `references/` or `scripts/` path that does not exist; a skill introduced by "which is" in the "Does NOT" part that does not exist |
| BROKEN | the routing map (routing.md) | a line outside the dialect; a lowercase node that is not a skill; a node with no class, an unknown class, or two classes; an edge to a node never declared; an unclosed `<!--`; a map file that cannot be read |
| BROKEN | a router's `rules.json` | not valid JSON, or not `{"rules": [...]}`; a rule without `when`, `skill` or `why`; a condition that is not a list of strings; a rule, `also`, `default` or case that names a missing skill; a case that routes somewhere other than its `expect` |
| BROKEN | gate rules (gates.md) | a `brain.json` `gates` entry that is malformed or names a missing skill; a `gates_off` entry without `path` or `why`; an unreadable `_meta/gates.json` |
| GAP | a convention not followed yet; reported, never blocking | no "Does NOT" clause naming a sibling; no `## Done when`; a body over 150 lines; a name without the brain's prefix; a skill neither drawn nor under `## Not drawn`; a drawn skill no entry node reaches; no call line, or one still reading `TODO` |
| ORPHAN | dead weight | a file under `references/` that `SKILL.md` never cites (citing a folder covers what is in it) |

A GAP left after your change gets one sentence to the person: what it is and why it stays. Adopted
skills often carry GAPs that nobody asked you to fix; name them, do not fix them unasked.

## The checks

```bash
_meta/brain routing sync                 # first: writes every Where block and the map's style lines
_meta/brain lint                         # skills, the routing map, routers' rules, gate rules
_meta/brain routing sync --check         # writes nothing; exit 1 when a block or style line is stale
_meta/brain route <router> --check       # each router whose rules or skills changed
```

- `routing sync --check` prints `BLOCK <file>: is out of date; run '_meta/brain routing sync'` for
  each stale file, then `routing sync: everything is up to date` when there is none.
- `route <router> --check` prints `ok     <router>: N rules, N cases`, or one BROKEN line per
  problem, and exits 1 on any.
- The pre-commit hook runs `lint` and `routing sync --check` again when a skill or
  `docs/ROUTING.md` is staged, and `route --check` when a `rules.json` is, so a check skipped here
  fails the commit later.

## rename-skill

```bash
_meta/brain rename-skill lab-backup-check lab-check-backups           # dry run: each file and its count
_meta/brain rename-skill lab-backup-check lab-check-backups --apply   # do it
```

With `--apply` it moves the folder (with `git mv` when it is tracked), fixes the frontmatter `name`,
and rewrites the name as a whole word (renaming `lab-a` leaves `lab-ab` alone) in `.claude/skills/`
(routers' `rules.json` included), `CLAUDE.md`, `README.md`, `docs/` (the map's node ids included;
`docs/RETRO-LOG.md` is history and is left alone), the brain's scripts and `brain.json` (the gate
rules), then runs `routing sync`. It refuses to rename a `brain-*` skill in a brain, to rename onto
a name that exists, and a new name without the brain's prefix. Afterwards, run the checks above and
read the new name in the files it listed: a whole-word rewrite can still change prose that used the
old name for something else.
