# Brain template: design

**Status:** approved, 2026-11-02.

## 1. Intent

A **brain** is a folder you start Claude Code sessions in, whose root is a git repo holding what
Claude needs to do one kind of work well: skills, the rules that bite, what has been learned, and
small scripts. The project repos and large files the work produces sit inside the same folder but
are not part of the brain.

This template is the starting point for every brain. It is distilled from three team brains that
have run on real work for months, keeping only what is independent of any team or domain. Each
brain made from it is built up as the work happens: it starts with no domain skills at all, and
grows through a small set of **meta skills** that write skills, scripts and facts the same way
every time. Those meta skills are the most important thing the template ships.

Intended brains, as test cases rather than features: a game-modding brain (a workspace of several
mod, tool and plugin repos plus tens of GB of generated assets, some of it not yet in git), an
open-source plugin maintainer brain (a few plugin repos plus test apps), and a homelab brain
(infrastructure repos, hostnames and addresses that must not leak).

### Why

- Knowledge that lives only in a workspace folder has no history and no backup. The game-modding
  workspace already has 16 skills and a large `docs/` tree, none of it in git.
- Skills written ad hoc drift: near-identical skills fire for each other, references never load,
  the same query gets rewritten every session. The source brains each fixed these the hard way;
  the fixes should not be rediscovered per brain.
- Brains must improve over time without each one diverging from the template's fixes.

## 2. Goals, non-goals, anti-goals

**Goals**

1. Create a new brain in one command, or turn an existing workspace folder into one without moving
   or overwriting anything already there.
2. Ship meta skills that make a brain grow well: `brain-write-skill`, `brain-write-script`,
   `brain-write-practice`, `brain-retro`, `brain-upstream`, `brain-sync`, `brain-setup`.
3. Let any brain pull later template improvements safely, touching only files the template owns.
4. Send improvements to the template back upstream through one dedicated path: `brain-upstream`
   in the brain records them, `template-intake` in the template takes them in (§6).
5. Make it structurally hard to commit what must not be committed: project repos, large generated
   files, secrets, private details.
6. Keep each brain's skills scoped to its own folder: a homelab session never sees game-modding
   skills, and no brain carries the skills used to work on the template itself.
7. Make routing forced and repeatable from the first skill (§7.7–7.9): every skill is placed in one
   routing map, routers decide by rule rather than judgement, and a gate blocks a skill's output
   unless that skill actually ran. The meta skills are gated from day one, so a skill can only be
   written through `brain-write-skill`, a script through `brain-write-script`, and so on.
   `brain-write-skill` is built around the map: placing a skill in the tree is part of writing it.

**Non-goals (v1)**

- Domain skills of any kind. The template ships only `brain-*` meta skills.
- Support for agents other than Claude Code (Cursor, Codex). The layout should not preclude it.
- Multi-user features: team/personal tiers, borrowing skills, packs, rosters, opt-in skills.
- The source brains' domain-specific routing detail: work records of a fixed shape, per-line
  exceptions for header edits, classification tables for one product's tickets. The template
  ships the mechanism; each brain supplies its own rules.
- Todo tracking and UI mods. Listed in §11 as possible later additions.

**Anti-goals: it is a failure, even if it works, if**

- it grows into a heavy CLI with dependencies or a build step (the template must run on stock
  `python3` and `bash`);
- any shipped file is specific to the organisations or teams the source brains came from (names,
  products, systems, colleagues);
- a brain has to edit a template-owned file to work, so updates start to conflict;
- running any command can stage a nested project repo, a large asset or a `.env` into the brain;
- it installs anything into `~/.claude/` (skills, commands, settings) or writes outside the brain
  folder, except the brain's own git hook;
- a brain session writes into the template, or a template session writes into a brain: they
  exchange suggestions only by reading each other (§6).

## 3. Concepts

| Term | Meaning |
| --- | --- |
| **Brain** | A folder whose root is a git repo containing `brain.json`. Sessions start at its root. |
| **Template** | This repo. It is itself a brain, with prefix `template`: its `template-*` skills work on the template, and the `brain-*` skills it ships are its product. |
| **Shipped** | What `new`, `adopt` and `update` copy into a brain: `_meta/**`, `.claude/skills/brain-*/**`, the managed blocks, and (once, at creation) the skeleton. |
| **Template-only** | Everything else in the template: `template-*` skills, its own `CLAUDE.md`, `README.md`, `brain.json`, `tests/`, `docs/`, `local/`. Never copied into a brain. |
| **Template-owned** | In a brain: `_meta/**`, `.claude/skills/brain-*/**`, and the managed block in `CLAUDE.md` and `.gitignore`. Overwritten by updates. Never edited inside a brain; a change one needs becomes an upstream suggestion. |
| **Brain-owned** | Everything else in the brain repo: `brain.json`, `CLAUDE.md` outside the managed block, the brain's own skills, `docs/`, `scripts/`, `.gitignore` outside the managed block. Never touched by updates. |
| **Prefix** | Short lowercase name for the brain's own skills (`se2-`, `lab-`). Shipped skills are always `brain-*`; `brain` and `template` are refused as a brain's prefix. |
| **Upstream suggestion** | One proposed change to a shipped file, recorded in a brain's `docs/UPSTREAM.md` by `brain-upstream` and answered in the template's `CHANGELOG.md`. |
| **Project folder** | Anything inside the brain folder that is not part of the brain: nested repos, assets, backups. Ignored by the brain's git. |
| **Practice** | One verified fact, with its level of evidence, when it was verified, and the command that re-checks it. |

## 4. Layout of a brain

```text
<brain>/                       sessions start here; this is the brain's git repo
  brain.json                   identity and conventions (brain-owned)
  CLAUDE.md                    managed block (template) + folder map and rules that bite (brain)
  README.md                    folder map for humans (brain)
  .gitignore                   managed allowlist block (template) + brain's own rules below it
  .env.example                 secret NAMES only, tracked; .env holds values, ignored
  .brain/                      ignored: this machine's local state (gate waiver log)
  .claude/
    settings.json              tracked; denies reading .env; wires the skill gate hooks
    skills/brain-*/            template-owned meta skills
    skills/<prefix>-*/         the brain's own skills (a router keeps its rules.json here)
    commands/                  only when the brain wants a typed entry point
  _meta/                       template-owned harness (see §7), incl. ROUTING-META.md and gates.json
  docs/                        brain-owned knowledge
    README.md                  index of docs/ folders
    ROUTING.md                 the routing map of the brain's own skills (§7.7)
    CAPABILITIES.md            what each system can and cannot do, dated
    RETRO-LOG.md               failures on real work and the change that fixed each
    UNCLASSIFIED-LOG.md        work no skill fit: the queue new skills come from
    UPSTREAM.md                proposed changes to template-owned files, and their answers
    practices/                 one file per fact, plus generated INDEX.md
    <anything else>            added when the first file lands (ideas/, design/, research/...)
  scripts/                     the brain's own scripts, with tests in scripts/tests/
  <project folders>            ignored: nested repos, assets, backups, decompiles...
```

### `.gitignore` is an allowlist

The managed block ignores everything at the root, then re-includes the brain paths:

```gitignore
# <!-- brain:begin --> managed by the brain template; edit below the end marker
/*
!/.gitignore
!/brain.json
!/CLAUDE.md
!/README.md
!/.env.example
!/.claude/
!/_meta/
!/docs/
!/scripts/
.env
.env.*
!.env.example
/.claude/settings.local.json
# <!-- brain:end -->
```

Rules the brain adds go below the end marker (e.g. `docs/private/`, `!/tools/scripts/` to track one
more folder). A new top-level folder is ignored until the brain opts it in.

### `brain.json`

```json
{
  "name": "homelab",
  "prefix": "lab",
  "description": "Running and changing my self-hosted infrastructure",
  "template": { "source": "/home/me/Github/Personal/Brain Template", "version": "0.1.0" },
  "scripts": { "python": "python3", "packages": "stdlib-only" },
  "privacy": {
    "deny_patterns": [],
    "max_file_kb": 1024,
    "large_file_allow": []
  },
  "practices": { "stale_after_days": 180 },
  "gates": [],
  "gates_off": []
}
```

- `gates` holds the brain's own gate rules and `gates_off` turns off a shipped one, each with a
  reason (§7.9).
- `.claude/settings.json` is brain-owned, except the hook entries that call `_meta/brain gate` and
  the `.env` deny entries: `new`, `adopt`, `init` and `update` write those and keep them current,
  and leave every other entry alone.

- `scripts.python` is the interpreter the brain's scripts and tests run with (`python3`, or e.g.
  `.venv/bin/python`). `scripts.packages` is `stdlib-only` or `allowed`; `brain-write-script` reads
  it instead of assuming either.
- `privacy.deny_patterns` are extended regexes the pre-commit guard blocks in staged content, for
  patterns that are safe to commit themselves: an address-range regex, a third party's proprietary
  file marker. **Patterns that would leak by being written down** (unreleased project names, real
  hostnames) go one per line in `.brain-private` at the root, which the allowlist ignores. The hook
  reads both. `brain.json` is excluded from the deny-pattern scan (it would match its own list) but
  not from the credential scan. If `privacy.private_file_expected` is true and `.brain-private` is
  missing on this machine, `doctor` warns that the guard is weaker here.
- `template.source` is the template's canonical location: its git URL once published, a local path
  until then. A per-machine override goes in `brain.local.json` (ignored), so a brain cloned on two
  machines does not carry one machine's home path.

### `CLAUDE.md`

The managed block (template-owned, refreshed by `update`) holds the rules every brain shares,
written for the agent:

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

Everything outside the block is the brain's: its folder map, its stages of work, its "rules that
bite" (e.g. "never commit third-party game assets", "one GPU job at a time").

## 5. Layout of the template repo (this folder)

```text
Brain Template/
  README.md                    what a brain is; new, adopt, update, upstream; the meta skills
  CLAUDE.md                    for sessions working ON the template (brain-* may be edited here)
  brain.json                   the template as a brain: prefix "template", role "template"
  .gitignore                   allowlist; local/ is ignored
  .claude/skills/brain-*/      the meta skills (shipped)
  .claude/skills/template-*/   skills for working on the template (template-only)
  _meta/                       the harness (shipped)
    brain                      single CLI entry point
    skeleton/                  brain-owned starter files, copied once at creation (incl. docs/ROUTING.md)
    ROUTING-META.md            the routing map of the brain-* skills (§7.7)
    gates.json                 shipped gate rules on the meta skills' files (§7.9)
    VERSION                    semver of the template
    CHANGELOG.md               one entry per version, citing the upstream suggestions it answers
  tests/                       harness tests and skill scenarios (template-only)
  docs/                        the template's own docs and this design (template-only)
  local/                       ignored: notes about the source brains; brains.txt
```

Only shipped paths reach a brain (§3). `local/brains.txt` lists, one absolute path per line, the
brains made from this checkout; `new` and `adopt` append to it, and `template-intake` reads it.
`new` and `adopt` run only from a template checkout (`brain.json` `role` is `template`); inside a
brain they refuse and say where to run them.

## 6. Lifecycle

### Setting up a brain

The template exists to cut the work of getting to a working brain, so setup is one short
conversation and the template does the rest, including leaving its own tooling behind. There are
three ways in; all end in the same state: the brain's first commit made, the hook installed,
`doctor` with no BLOCK, and no template-only file present.

| Starting from | Say | Skill → command |
| --- | --- | --- |
| A session in the template | "make a brain for X at <path>" | `template-make-brain` → `new` |
| A session in the template | "turn <folder> into a brain" | `template-make-brain` → `adopt` |
| A session in a copy of the template (git clone, GitHub "Use this template", a copied folder) | "set this up" | `brain-setup` → `init` |

Setup asks four things: the name, the prefix (suggested from the name), a one-line description,
and whether anything must never be committed (written to `.brain-private`). Everything else takes
the defaults in §4 and can be changed later in `brain.json`. Each command runs with `--dry-run`
first and the skill shows the result before anything is written.

### New brain

`_meta/brain new <dir> --name N --prefix P [--description D] [--python PATH --packages allowed] [--dry-run]`

1. Refuse if `<dir>` exists and is not empty (that is `adopt`).
2. Copy shipped files and the skeleton (never template-only files); fill `brain.json`; write the
   managed blocks.
3. `git init`, install the pre-commit hook (§7.3), make the first commit
   (`meta(brain): initialise from template vX.Y.Z`).
4. Append the brain's path to the template's `local/brains.txt`.
5. Run `doctor`; print what to do next (open a session in `<dir>`).

### Turn a copy of the template into a brain

`_meta/brain init --name N --prefix P [...] [--dry-run]`, run inside the copy.

1. Refuse unless the folder is an unchanged copy of the template: `brain.json` `role` is
   `template`, and if it is a git repo, the working tree is clean. Refuse if `local/` exists: a
   working template checkout keeps its notes there, and a clone never has one because it is
   ignored. This is what stops `init` converting the template itself.
2. Remove the template-only paths (§3), then write the skeleton, `brain.json`, managed blocks and
   manifest. Record `template.source` (the copy's `origin` when that is the template, otherwise the
   canonical location from the template's own `brain.json`) and `template.version`.
3. History: a plain clone of the template has the template's commits and its `origin`; start a
   fresh history so the brain does not carry them, but only when every commit is on that remote,
   so nothing is lost. A repo made with "Use this template", or a folder with no repo, keeps or
   gets its own history.
4. Install the hook, make the first commit, run `doctor`.

`--dry-run` lists what would be removed and written, and changes nothing.

### Adopt an existing folder

`_meta/brain adopt <dir> --name N --prefix P [...] [--dry-run]`

**Never moves, renames, overwrites or deletes an existing file.** It only adds files and inserts
managed blocks.

1. **Inventory** and print it: nested git repos **at any depth** (a real workspace has ~30, all two
   or three levels down; stop descending once inside one), each with remote / no remote / unpushed;
   top-level folders over a size threshold; existing `.claude/skills/`, `CLAUDE.md`, `docs/`,
   `.env`; an existing root `.git`.
2. Write missing brain files from the skeleton. An existing file is kept; the skeleton's version is
   reported, not written. `docs/` log files are created only if absent.
3. Insert the managed block at the top of `CLAUDE.md` and `.gitignore` (creating them if absent).
   Existing lines are kept below the block.
4. Existing `.env`: keep it, make sure it is ignored, and write `.env.example` with its key names
   only (if `.env.example` is absent).
5. `git init` if the root is not a repo; install the hook; append the folder's path to the
   template's `local/brains.txt`.
6. **Stop before committing.** Print what `git add -A` would stage (file count, total size, the
   largest files, any file over `max_file_kb`). `template-make-brain` walks through that list with
   the person and makes the first commit only on a yes, then drafts the folder map in the brain's
   `CLAUDE.md` from the inventory.

`--dry-run` makes no change at all, including no `git init`; a test asserts it writes nothing.

### Update from the template

`_meta/brain update [--from PATH|URL] [--ref REF] [--dry-run]`

**Source of truth is the template's committed history, never its working tree.** `update` reads
the source's default branch at its latest commit (or `--ref`, a tag or sha). Uncommitted template
edits never reach a brain. There is no separate release step: commit in the template, then update.
A local-path source is read with `git archive`; a URL source is shallow-cloned into an OS temporary
directory that is removed afterwards (temporary files are not "writing outside the brain").

1. Refuse if a template-owned file has uncommitted changes, or differs from the brain's
   `_meta/MANIFEST.sha256`: that is a local edit to template code. Print the files and stop;
   `brain-upstream` records the change as a suggestion, then restores the file.
2. Replace template-owned paths with the source's: add, change, and remove files that the template
   removed (only inside template-owned paths).
3. Rewrite the managed blocks in `CLAUDE.md` and `.gitignore`.
4. Write `_meta/MANIFEST.sha256` from the files just copied (`new` and `adopt` do the same), so the
   local-edit check always compares against what was actually installed.
5. Record `brain.json` `template.version` as `<VERSION>+<short sha>`. Print the diff summary, the
   `CHANGELOG.md` entries newer than the previous version, and which of this brain's open upstream
   suggestions they answer. **Do not commit**; `brain-sync` does.

A skeleton change does not reach existing brains (skeleton files are brain-owned once copied);
`update` prints skeleton files that changed since the brain's version so the person can merge by
hand if they want.

### Sending a change upstream

A brain never edits a template-owned file, and the template never writes into a brain. They
exchange suggestions by reading each other:

1. **In the brain**, `brain-upstream` writes one entry in `docs/UPSTREAM.md`: a `## <id>` heading
   (`YYYY-MM-DD-<slug>`), then the installed template version, the file or files, what went wrong
   or could be better, the proposed change (prose, or a diff against the installed file), and
   `status: open`. It is written for any brain, with no hostnames, project names or other details
   private to this one, because the answer lands in a public template; the privacy guard checks
   it like any other file. Other skills hand off to it: `brain-retro` when the failing skill is a
   `brain-*` skill or the fault is in `_meta/`; `brain-write-skill` and `brain-write-script` when
   the change belongs in the template; `update` and `doctor` when they find a local edit to a
   template-owned file.
2. **In the template**, `template-intake` collects open entries from the brains in
   `local/brains.txt` (or a path it is given, such as a clone of a brain kept on another machine).
   For each one the person accepts, it makes the change in the template, with its tests, and adds a
   `CHANGELOG.md` entry citing the id. A declined suggestion gets a `CHANGELOG.md` line with the id
   and a one-line reason. Committing in the template is enough; there is no release step.
3. **Back in the brain**, the next `update` reports the answered ids, and `brain-sync` marks each
   entry `landed <version>` or `declined: <reason>` in the same `meta(brain)` commit.

### Sync

`brain-sync` (a skill, §8) wraps `git status`, the checks in §7.6, commit with a scoped subject,
pull with rebase, push. Pushing happens only when the person asks.

## 7. The harness (`_meta/`)

One executable, `_meta/brain`, Python 3.9+ standard library only, with subcommands. It is the
only harness entry point; the git hook is a two-line shim that calls it. Must run on Linux and
macOS (no GNU-only flags when shelling out; prefer Python).

| Subcommand | Purpose |
| --- | --- |
| `new`, `adopt`, `init`, `update` | §6 |
| `doctor [--quick]` | Read-only health check (§7.1) |
| `lint` | Skill and routing-map checker (§7.2, §7.7) |
| `routing sync [--check]`, `routing show [SKILL]` | Regenerate each skill's "Where this sits" block; print the tree around one skill (§7.7) |
| `route RULES --set FIELD=VALUE... [--check]` | Apply a router's rules file and name one skill (§7.8) |
| `gate record\|check\|waive\|status` | The skill gate's hook commands and its one-shot waiver (§7.9) |
| `hook pre-commit`, `hook install`, `hook self-test` | Privacy guard (§7.3) |
| `practices lint\|index [--check]\|candidates\|search` | Practices store (§7.4) |
| `rename-skill OLD NEW [--apply]` | Rename a skill everywhere (§7.5) |
| `env-sync` | Add keys missing from `.env.example` to `.env` as empty lines; never print values |

### 7.1 `doctor`

Read-only. Each line is `ok`, `WARN` or `BLOCK`; exit 1 if anything blocks.

- Tools: `git`, `python3`, the configured `scripts.python`.
- `brain.json` present and valid; prefix set.
- No template-only file (a `template-*` skill, the template's `tests/`) and `role` is not
  `template` (BLOCK: this is a copy of the template that was never set up; run `brain-setup`).
- Template-owned files match `MANIFEST.sha256` (WARN listing edits). Template version behind the
  source's, when the source is reachable (WARN).
- Pre-commit hook installed, and `core.hooksPath` not bypassing it.
- `.claude/settings.json` denies reading `.env` and wires both gate hooks (WARN if not: skills
  can then be imitated from memory); gate rules valid and every skill they name exists.
- Every router's `rules.json` passes `route --check`.
- `.env` mode 600 if present; keys in `.env.example` missing from `.env` (WARN, names only).
- `lint`: BROKEN blocks, GAP warns with a count.
- `practices lint`: errors block; stale entries warn.
- Scripts tests pass under `scripts.python` (skipped with `--quick`).
- The brain repo: no remote, uncommitted or unpushed work (WARN).
- Nested repos: no remote, or unpushed commits (WARN, one line each). This is the "work you would
  lose if the disk died" list.
- `docs/README.md` mentions every `docs/` subfolder (WARN).
- Tracked files over `max_file_kb` not in `large_file_allow` (WARN).

### 7.2 `lint` (skills)

Over `.claude/skills/*/SKILL.md`. Severities: **BROKEN** (loads wrongly or not at all; fails the
run), **GAP** (a convention not yet followed), **ORPHAN** (dead weight).

- BROKEN: missing frontmatter `name` or `description`; `name` ≠ folder; duplicate names; a
  `SKILL.md` nested deeper than one level; description over 1024 characters; a cited path starting
  `references/` or `scripts/` (resolved relative to the skill folder) that does not exist; a skill
  named in a "Does NOT … that is X" clause that does not exist. Other paths in a skill are often
  relative to the brain root or a project folder and are not checked.
- GAP: no "Does NOT" clause naming a sibling; no `## Done when` section; body over ~150 lines; a
  brain skill not starting with `<prefix>-`.
- ORPHAN: a file in `references/` that `SKILL.md` never cites.
- Routing-map checks are part of the same run (§7.7).

Adopted skills will mostly show GAPs; that is expected and must not block.

### 7.3 Pre-commit guard

Blocking. Checks only staged content:

- Staged `.env` or `.env.*` other than `.env.example`.
- Credential shapes: private key headers, common token prefixes (GitHub, AWS, Slack, OpenAI and
  Anthropic style keys), `password=`/`token=`/`api_key=` followed by a literal value.
- Any `privacy.deny_patterns` match.
- A staged file over `max_file_kb` not in `large_file_allow`.
- A staged path inside a nested git repo (should be impossible with the allowlist; defence in
  depth).
- When skills or `docs/ROUTING.md` are staged: `lint` must have no BROKEN and
  `routing sync --check` must pass. When a `rules.json` is staged: `route --check`. When practices
  are staged: `practices lint` and `practices index --check`.

`hook self-test` plants one case per rule in a temporary repo and proves each blocks.
`hook install` links the shim into the repo's common git dir (works for worktrees) and refuses to
replace a hook that is not its own.

### 7.4 Practices store

Generalised from the source brain that ran it longest. One file per fact in `docs/practices/`,
`kebab-case-id.md`:

```yaml
---
id: kebab-case-id            # must equal the filename
tags: [a, b]                 # non-empty
durability: durable | volatile
evidence: researched | reproduced | reliable
verified: YYYY-MM-DD
source: <free text: commit, issue URL, forum post, log path>; 2+ entries (comma-separated) for reliable
recheck: <command or URL>    # required when volatile
reproduced-by: <how>, YYYY-MM-DD   # required at reproduced and reliable
reviewed-against: [ids]      # required; [] means nothing was close
---
```

- `researched`: read from source, docs or a statement; nobody watched it happen. **Reading code is
  `researched`.** `reproduced`: observed running. `reliable`: held across two or more occasions.
- Body: the point in one or two lines, the specifics, what it means for the work. `[[id]]` links
  must resolve.
- `index` writes `docs/practices/INDEX.md` (generated, do-not-edit header, tally by evidence, stale
  list, one row per entry with its first sentence). `candidates` ranks likely duplicates by tag and
  word overlap. `search` is the way to look things up.
- `docs/practices/README.md` (skeleton) documents the schema; a harness test asserts it names every
  field the linter enforces, so the two cannot drift.

### 7.5 `rename-skill`

Dry run by default. With `--apply`: `git mv` the folder, fix frontmatter `name`, rewrite every
reference in `.claude/skills/` (including routers' `rules.json`), `CLAUDE.md`, `README.md`,
`docs/` (including `ROUTING.md` node ids; except `RETRO-LOG.md`, which is history), `scripts/` and
the `gates` in `brain.json`, then run `routing sync`. Refuses to rename a `brain-*` skill inside a
brain.

### 7.6 Checks before commit (what `brain-sync` runs)

```bash
_meta/brain lint                      # skills and the routing map
_meta/brain routing sync --check
_meta/brain practices lint
_meta/brain doctor --quick
<scripts.python> -m unittest discover -s scripts/tests -t scripts   # when scripts/ changed
```

### 7.7 The routing map

**One map says which skill hands to which, and every skill is in it.** The brain's own skills are
drawn in `docs/ROUTING.md` (brain-owned, from the skeleton); the `brain-*` skills are drawn in
`_meta/ROUTING-META.md` (template-owned). The harness reads both as one graph, so a brain's diagram
can hand on to `brain-write-practice` or `brain-retro`.

The map is Mermaid inside Markdown, so it renders on GitHub and reads without a tool, in a strict
dialect that the lint enforces. The dialect turns the parsing traps the source brains hit into
errors:

- One `flowchart` per section. **A node whose id is lowercase is a skill, and its id is the
  skill's name.** Any id starting with a capital letter is something else: an entry trigger, a
  decision, a person acting, a store.
- Ids are shared across every diagram in both files: the same id in two diagrams is the same node.
  That is how one diagram continues another, so it must be deliberate.
- Each node gets a class on first appearance, from a fixed set: `entry`, `gate`, `work`,
  `optional`, `decision`, `state`, `human`. `routing sync` inserts the style lines, so authors only
  write `:::gate`.
- `-->` is a call; `-.->` a call that happens only sometimes; `|label|` says when.
  **Edges are calls, not cross-references.** A skill's "Does NOT … that is X" clause is a boundary
  and is not drawn; a map built by grepping skill names says nothing.
- **A gate's class is its phase; the arrows between gates are layout, not order.** Every gate on
  a path runs every time, in any order, including when it comes back clean. A gate that was
  skipped and a gate that found nothing look identical afterwards, so its result is recorded
  either way (§7.8).
- A skill that is deliberately not drawn goes in a `## Not drawn` table with the reason, so
  "missing" always means "nobody drew it".

**`lint`** adds, as BROKEN: a lowercase node that is not a skill; a node with no class or an
unknown one; an edge to a node never declared; a `gates` rule or a router's rules naming a missing
skill. As GAP: a skill neither drawn nor in `## Not drawn`; a skill no entry node reaches; a
missing "Call it directly when:" line, or one still reading `TODO`.

**`routing sync`** writes each brain skill's `## Where this sits` block between generated
markers, from the graph contracted through non-skill nodes (so `router → decision → three skills`
resolves to three hand-ons): **Runs after**, **Hand to next**, a fixed notice when the skill is a
gate, and the paths the gate reserves for it (§7.9). Generated because hand-written sequence lines
drift the first time an edge moves, and a stale one reads as authoritative. It never writes
template-owned skills; their blocks come from `ROUTING-META.md` in the template.

**Call it directly when:** sits under the block, outside the markers, and is written by hand: the
deliberate way into the tree mid-flow, naming any earlier step that still applies. `sync` inserts a
`TODO` line where it is missing, which `lint` reports.

`routing show [SKILL]` prints entry points, isolated skills, and one skill's neighbours, for the
meta skills to use while placing a new skill.

### 7.8 Routers

A **router** is a skill at an entry point that fans out to three or more skills by kind of input.
`brain-write-skill` writes one when that shape appears, from a reference in the skill. A router:

- **routes only**: it never does the work it hands on;
- **extracts fields** from the input (by reading: that is the judgement part), then runs every
  gate on the path and records each result, including clean ones, as a `Checked` list wherever
  the brain keeps its work, or in the conversation if it keeps none;
- **decides by rule**: `_meta/brain route <router>/rules.json --set kind=... --set repo=...`
  returns the one skill (plus any to offer alongside) and the rule that matched. The router never
  overrides it by judgement; a wrong route means a wrong rule, fixed in the rules file. This
  exists because routing by reading sent the same input to different skills on different days.

`rules.json` (brain-owned, in the router's folder) is ordered, first match wins:

```json
{
  "default": "brain-retro",
  "rules": [
    { "when": { "kind": ["block", "model"] },        "skill": "se2-build-block", "why": "..." },
    { "when": { "kind": ["script"], "title~": ["api"] }, "skill": "se2-write-script-mod",
      "also": ["se2-check-api-docs"], "why": "..." }
  ],
  "cases": [ { "input": { "kind": "block" }, "expect": "se2-build-block" } ]
}
```

A condition holds when the field's value is any listed one; `field~` matches a substring, case
insensitive; a rule matches when all its conditions hold. No match means `default`, which is
`brain-retro` unless the brain says otherwise, so unrouted work becomes an `UNCLASSIFIED-LOG.md`
row. `route --check` validates the file, runs every `cases` entry, and fails if a named skill does
not exist.

### 7.9 The skill gate

**Reading a skill is not running it.** A skill read as reference and imitated from memory skips
everything in its `references/`, silently, and an instruction does not fix that: it is exactly the
kind of thing that gets talked past. The gate is a hook, so it does not depend on the judgement
that failed. It is friction and visibility, not a security boundary: anything with a shell can get
round it, and the point is that doing so is deliberate, single-use and visible.

- **Wiring** (in `.claude/settings.json`): `PostToolUse` on `Skill` runs `_meta/brain gate record`,
  which notes the skill against the session id in the OS temp directory. `PreToolUse` on `Write`,
  `Edit` and `Bash` runs `gate check`. For `Bash` it pulls the target out of redirections, `tee`,
  `cp`, `mv` and `sed -i`; a heuristic, deliberately, because a gate whose easiest bypass is the
  tool you reach for anyway is not a gate.
- **Rules** are a path glob (relative to the brain root, may reach into project folders), the
  skill or skills that own it, `spend_on_revision`, and `why`. Shipped rules live in
  `_meta/gates.json`; the brain's own in `brain.json` `gates`; `gates_off` turns a shipped one off
  with a reason; `gate_exempt` globs (e.g. an archive folder) are never checked.
- **Check:** a path no rule matches passes at once. A matching path passes if an owning skill ran
  this session. With `spend_on_revision`, creating the file is free and every edit of an existing
  one spends that run, so the next edit needs a fresh invocation: for outputs where every revision
  has to go through the skill's review again. Otherwise the write is refused with a message naming
  the skill to invoke and the rule's `why`.
- **Waiver:** `_meta/brain gate waive <skill> "<reason, and who said so>"`, only on the person's
  express say-so. It is one-shot, consumed by the next matching write, announced as a system
  message when used, and logged to `.brain/gate-waivers.log`.
- `gate status` prints what ran this session, any armed waiver and the last refusal.
- If the gate itself errors, it lets the write through with a visible warning rather than
  blocking every tool call.

**Shipped rules make the meta skills forced from day one:**

| Path | Owning skill |
| --- | --- |
| `.claude/skills/<prefix>-*/**` | `brain-write-skill` |
| `docs/ROUTING.md` | `brain-write-skill` |
| `scripts/**`, `docs/CAPABILITIES.md` | `brain-write-script` |
| `docs/practices/**` | `brain-write-practice` (the generated `INDEX.md` is written by the harness, which the gate never sees) |
| `docs/RETRO-LOG.md`, `docs/UNCLASSIFIED-LOG.md` | `brain-retro` |
| `docs/UPSTREAM.md` | `brain-upstream`, `brain-sync` |

In the template, the first row also covers `.claude/skills/brain-*/**` and
`.claude/skills/template-*/**`.

Like the `.env` deny, the gate only applies to sessions started at the brain root (§13, item 7).

## 8. The skills

Every skill, shipped or template-only, is under ~100 lines with detail in `references/`, has a
description stating when not to fire and naming its sibling, and has a `## Done when` section.
They read `brain.json` and `CLAUDE.md` for brain-specific conventions instead of hard-coding any.

### Shipped meta skills (`brain-*`, in every brain)

| Skill | Does | Does NOT |
| --- | --- | --- |
| `brain-write-skill` | Create, change, split or rename one of the brain's skills, **starting from where it sits in the routing map**; write or extend a router when an entry point fans out; gate the skill's output when it must not be improvised. Sequence below. | Write scripts (`brain-write-script`); record facts (`brain-write-practice`); change a `brain-*` skill (`brain-upstream`) |
| `brain-write-script` | Decide whether code earns a file (written twice, encodes a non-obvious fact about a system, touches data that matters, took minutes to work out); place it by the system it touches (`scripts/<system>/`, `scripts/common/` for two or more, a skill's own `scripts/` only if that skill is the sole caller); no hardcoded home paths (resolve from the brain root); read-only unless the name says otherwise, with a test asserting it; secrets from the environment, never in argv, masked in output; **probe the system first and record what it can and cannot do in `CAPABILITIES.md`, negatives included and dated**; tests for logic and refusal paths, not the network; follow `brain.json` `scripts`. | Write skills; run anything destructive the person has not asked for; change `_meta/` (`brain-upstream`) |
| `brain-write-practice` | Two gates (would a second occurrence go faster with it; is it a fact rather than a rule about how to work); set evidence honestly; run `candidates`, rule each as distinct, merge or supersede (never delete; supersede); write; `index`; `lint`. Includes a periodic sweep for stale entries. | Write rules about how to work (those go in the skill that governs the work) |
| `brain-retro` | When a skill just went wrong: one row in `RETRO-LOG.md` (failure → fix or "open"). If the skill is the brain's own, one concrete proposed edit to it, applied through `brain-write-skill` on a yes; if it is a `brain-*` skill or the fault is in `_meta/`, hand to `brain-upstream`. Two routing failures get their own fix: output written while its skill never ran, or a skill imitated rather than invoked, means a missing gate rule; the same kind of input going to different skills means a missing router rule. When work fit no skill (including a router's `default`): one row in `UNCLASSIFIED-LOG.md` with what a skill would have needed. Suggests `brain-write-skill` when the same kind of row appears twice. | Write the skill itself (`brain-write-skill`); edit template-owned files |
| `brain-upstream` | Record one proposed change to a shipped file in `docs/UPSTREAM.md` (§6), free of this brain's private details; if a template-owned file was edited locally, restore it once recorded (on a yes); list open suggestions and their answers. | Edit template-owned files; write into the template |
| `brain-sync` | Show where the brain stands; run §7.6; commit with a scoped subject (`skill(<name>)`, `script(<system>)`, `docs(<area>)`, `practice(<id>)`, `meta(brain)`), never mixing a template update with other changes in one commit; pull with rebase; push only when asked; after `update`, review and commit the template change and mark answered suggestions. | Change template-owned files; touch nested project repos |
| `brain-setup` | In a copy of the template: turn it into a brain (`init`), asking the setup questions (§6), showing the dry run and committing on a yes. In a brain: explain what is here, run `doctor` and repair what it reports, run `update`. | Create or adopt a brain from the template (`template-make-brain`); write domain skills (`brain-write-skill`) |

### `brain-write-skill`, in order

The most important skill the template ships. Distilled from the source brain that ran longest,
whose skills are tuned for repeatable outcomes; its domain detail stays behind and the sequence
comes over. Detail lives in `references/conventions.md` (file shapes, frontmatter, checks),
`references/routing.md` (the map dialect, the router pattern, `Checked` lists) and
`references/gates.md` (when to gate, rule shape, waivers).

1. **Does it earn a skill?** Work that will happen again and is not obvious to do well: a sequence
   someone would reinvent, or judgement someone would get wrong. A fact is a practice
   (`brain-write-practice`), a query or helper is a script (`brain-write-script`), and something
   done once is neither.
2. **Place it in the tree before writing it.** `routing show`: where does this work enter (an
   existing entry point, or a new entry node), what must run before it, what it hands to, whether
   it is a gate on someone's path, and whether it ends where a person acts. If an entry point now
   fans out to three or more skills by kind of input, write or extend a router (§7.8), with a rule
   and a test case for the new skill. Draw it in `docs/ROUTING.md`.
3. **Name it** `<prefix>-<verb>-<object>`, matching the brain's existing families. Never rename by
   hand (`rename-skill`).
4. **Description:** what it does; when to use it, in the words a person would actually say; and
   what it does NOT do, naming the sibling. Routers and other skills read descriptions to decide,
   and `lint` checks the names resolve.
5. **Body**, about 100 lines:
   - the sequence and the judgement inline;
   - every must-obey rule inline, because `references/` do not auto-load and a rule left there is
     a rule skipped;
   - lookup material in `references/`, behind an explicit "Read `references/x.md`" at the step
     that needs it;
   - why a step matters rather than one more imperative, since the reason is what survives a case
     the author never saw;
   - where its output goes (a project folder, `docs/`, outside the brain), or the next agent puts
     it wherever it is standing;
   - `## Where this sits` (from `routing sync`) and a hand-written "Call it directly when:" line;
   - `## Done when`, as conditions someone can check.
6. **Gate its output** when it must not be improvised: anything that leaves the brain (a post, PR
   or release text, config applied to a live system, a reply to someone), or anything a later step
   trusts. Add the rule to `brain.json` `gates`, with `spend_on_revision` when every revision needs
   the skill's review again. A path no rule covers is unguarded.
7. **Check:** `lint` with no BROKEN (and its GAPs explained), `routing sync --check`, and
   `route --check` if a router changed.
8. **Run it on a real case before trusting it.** Two runs that read a step differently mean that
   step is not doing its job. Fix it by explaining why, not by adding emphasis.
9. Hand any script it needs to `brain-write-script`, then commit through `brain-sync`.

A skill that grew past ~150 lines, or that has two entry points, is split by where its parts sit in
the tree, not by topic.

### Template-only skills (`template-*`, never copied into a brain)

| Skill | Does | Does NOT |
| --- | --- | --- |
| `template-make-brain` | Create a brain (`new`) or adopt a folder (`adopt`): ask the setup questions (§6); show the dry run; for adopt, walk through the inventory and staging list and get a yes before the first commit, then draft the brain's `CLAUDE.md` folder map from the inventory; end by saying which folder to open a session in. | Set up a copy of the template (`brain-setup`, run in the copy); repair an existing brain (`brain-setup`, run in that brain) |
| `template-intake` | Collect open upstream suggestions from the brains in `local/brains.txt` or a path given, skipping ids `CHANGELOG.md` already answers; with the person, accept or decline each; make an accepted change through `brain-write-skill` or `brain-write-script`, written for any brain, with tests; add the `CHANGELOG.md` entry citing the id. Read-only toward brains. | Write into a brain; commit (`brain-sync`) |

In the template, sessions use the shipped `brain-*` skills on the template itself. There
`brain-write-skill` asks whether a new skill ships (`brain-*`) or stays in the template
(`template-*`), and editing a `brain-*` skill directly is allowed: the template's own `CLAUDE.md`
says so, and it has no managed block.

## 9. Testing

Harness tests in `tests/` (Python `unittest`, stdlib), all in temporary directories:

- `new` produces a brain on which `doctor` has no BLOCK and `lint` has no BROKEN, containing no
  template-only file; it refuses the prefixes `brain` and `template`, refuses to run outside a
  template, and appends the brain's path to `local/brains.txt` (in a temporary template copy).
- `init` on a fresh clone of the template removes every template-only path, keeps every shipped
  one, and starts a fresh history; it refuses when `local/` exists, on a dirty tree, and when a
  commit is not on the remote; `--dry-run` writes nothing. `doctor` blocks on a copy never set up.
- `adopt --dry-run` writes nothing (snapshot the tree before and after). `adopt` on a fixture
  workspace (nested repos with and without remotes, a large folder, an existing `CLAUDE.md`,
  `.gitignore`, `.env` and skills) changes no existing file outside the managed blocks, and its
  staging preview excludes nested repos, the large folder and `.env`.
- `update` changes only template-owned paths; refuses on a locally edited template file; removes a
  file the template deleted; never copies an uncommitted template edit; reports which open
  `docs/UPSTREAM.md` ids the new `CHANGELOG.md` entries answer.
- `hook self-test` passes; each rule has a planted case.
- `practices lint` accepts the skeleton's example and rejects each missing required field;
  README/schema parity.
- `lint` flags each BROKEN case; adopted-style skills produce GAPs, not BROKEN.
- `rename-skill` rewrites references, `ROUTING.md` node ids, `gates` and routers' rules, and
  leaves `RETRO-LOG.md` alone.
- Routing map: `lint` flags each BROKEN and GAP case in §7.7 with a planted map; contraction walks
  through decision nodes (`router → decision → three skills` gives three hand-ons); the same id in
  two diagrams joins them; `routing sync` is idempotent, leaves "Call it directly when:" lines
  alone, never touches a `brain-*` skill, and `--check` fails on a stale block.
- `route`: first match wins; every condition must hold; `~` matches substrings; no match gives
  `default`; `--check` fails on a missing skill or a failing case.
- Gate, driven with recorded hook payloads: a write to an unruled path passes; a ruled path is
  refused until its skill is recorded, then passes; `spend_on_revision` lets creation through and
  spends a run on each edit; a waiver works once, is logged, and is announced; `Bash` redirections,
  `tee`, `cp`, `mv` and `sed -i` into a ruled path are caught; `gates_off` and `gate_exempt` work;
  the shipped rules refuse a new `SKILL.md` until `brain-write-skill` has run; an internal error
  lets the write through with a warning.
- `new`, `adopt` and `init` wire the gate hooks and `.env` deny entries into
  `.claude/settings.json` and keep any entries already there; `update` refreshes only those.
- **Origin check:** no tracked, shipped file mentions the source brains' organisation, products,
  systems or people. The term list lives in `local/` (ignored) so the check itself leaks nothing;
  the test skips with a notice when that file is absent.

**Skill scenarios.** `lint` proves only a skill's shape. Each skill, shipped and template-only, is
also run once by a fresh subagent on a scripted scenario in a brain made by `new` in a temporary
directory (for example "make a skill for checking my backups", "I keep rewriting this query",
"record that the router drops mDNS across VLANs", "this `brain-*` skill missed a step", and, once
three work skills exist, "everything I bring in should go to the right one of these"). It passes
when the output follows §8 (lint clean, the skill placed in `ROUTING.md`, a router with rules and
cases where one was called for, files where §4 puts them, the right commit scope) and the
`brain-*` skill fired rather than a globally installed lookalike. One more scenario asks for a
quick skill edit without naming any skill, and passes only if the gate refuses the write and the
session then invokes `brain-write-skill` instead of asking for a waiver. Scenarios are kept as prose in
`tests/scenarios/` and re-run when a skill changes materially. No repeated-run variance checks in
v1.

## 10. Verification against the three intended brains

Done once the build is complete, writing only to temporary directories:

1. **Homelab** (`--prefix lab`): `new`; add a placeholder `deny_patterns` entry for a private
   address range; confirm the hook blocks a staged file containing one. Then grow a small tree
   through `brain-write-skill`: three skills behind one entry point, which should produce a
   `lab-router` with rules and cases, a gate on the one skill whose output is applied to a live
   system, a clean `lint`, and generated "Where this sits" blocks.
2. **Plugin maintainer** (`--prefix` chosen then): clone the template and set it up with `init`,
   the copy route; add two plugin repos and a test app as nested repos; confirm `doctor` lists
   them and the brain stages none of them.
3. **Game modding**: `adopt --dry-run` against the real workspace folder (read-only, verified by
   snapshot of its top-level listing and mtimes), and a real `adopt` on a fixture copy of its
   shape (skills, `CLAUDE.md`, `.gitignore`, `.env`, nested repos, a large folder). Report the
   inventory and staging preview the real folder would get, and the routing GAPs its existing
   skills would show (expected: all undrawn until placed).
4. **Upstream round trip**: in the homelab brain, `brain-upstream` records a suggestion against a
   `brain-*` skill; `template-intake` in a temporary clone of the template accepts it and commits;
   `update` from that clone brings it into the brain, and `brain-sync` marks it landed. The real
   template is not changed by this check.

The real game-modding folder is not adopted as part of this work; that is the person's call
afterwards, through `template-make-brain`.

## 11. Possible later additions (not v1)

A todo tracker with verify commands. A glossary file in
the "Avoid / Not / Owned by" shape, created when a brain first has a misleading term
(`brain-write-practice` can mention the format meanwhile). Typed entry-point commands. Agent
portability (`.agents/skills/` with a symlink).

## 12. Left to the builder

- Module structure inside `_meta/`, and how the `brain` CLI is split internally.
- Exact credential regexes, size thresholds for "large folder" in the inventory, default
  `max_file_kb` (1024 suggested).
- Wording of skills and references, within §8.
- Skeleton file contents beyond the shapes in §4 and §7.4.

## 13. Calls made in design (for the person to check)

1. The brain repo root **is** the workspace folder (not a separate repo linked in), and skills live
   as real folders in `<brain>/.claude/skills/`. Nothing goes into `~/.claude/`.
2. `docs/` holds the brain's knowledge, logs and practices (matches the existing modding
   workspace, so adopting it renames nothing).
3. Updates copy template-owned paths from a template checkout, guarded by a hash manifest, rather
   than a git merge from a template remote.
4. Harness written in Python standard library behind one `_meta/brain` command, instead of the
   source brains' bash scripts: easier to test and to keep portable.
5. Secrets: a per-brain `.env` (ignored) with a tracked `.env.example`, denied to the agent in
   `.claude/settings.json`.
6. The source brains' separate practice-review skill is folded into `brain-write-practice`, and
   their "skill gap" idea (propose one edit to the skill that just failed) into `brain-retro`, for
   the brain's own skills; for a `brain-*` skill it becomes an upstream suggestion.
7. Sessions are expected to start at the brain root. Per the Claude Code docs, project skills load
   from each parent directory up to the repository root, and `.claude/settings.json` is read only
   from the session's starting directory. So a session started in a plain subfolder of the brain
   should see its skills, but one started inside a nested project repo likely will not, and will
   not get the brain's `.env` deny either. The workaround is `--add-dir <brain>`; the template's
   `README.md` says so. Not otherwise handled in v1.
8. The `.env` deny is `"Read(./.env)"` and `"Read(./.env.*)"` in `permissions.deny`. Claude Code
   applies it to recognised Bash file commands (`cat`, `head`, redirections) too, but not to a
   script that opens the file itself, so the managed `CLAUDE.md` rule still matters.
9. Privacy patterns are split: ones safe to commit in `brain.json`, ones that would leak by being
   written down in an ignored `.brain-private`.
10. `update` reads the template's latest commit, not tagged releases and never uncommitted edits;
    the install manifest is written by `new`/`adopt`/`init`/`update` from what they copied.
11. When a global skill overlaps a `brain-*` skill, the managed `CLAUDE.md` block and the `brain-*`
    descriptions send the work to the `brain-*` skill.
12. Skills for working on the template use the template's own prefix, `template-*`, and never
    reach a brain. Leaving them behind is part of setup on every route, including a plain clone
    or "Use this template" copy (`init` removes them), and `doctor` blocks on a copy that was never
    set up. Creating and adopting brains moved out of `brain-setup` into `template-make-brain` for
    the same reason; `brain-setup` keeps the copy route and the in-brain repair work.
13. Upstream path: a brain records suggestions in its own tracked `docs/UPSTREAM.md`
    (`brain-upstream`); the template reads them (`template-intake`, brain paths in its ignored
    `local/brains.txt`) and answers in `CHANGELOG.md`, which `update` already brings back. Neither
    side writes into the other.
14. `init` guards against converting the template itself by refusing when `local/` exists, and
    starts a fresh history for a plain clone only when every commit is on the template's remote.
15. Each skill is proven by one scripted scenario run by a fresh subagent (§9); no repeated-run
    variance testing in v1. You did not pick on this one; it is my recommendation and easy to
    change.
16. Forced routing is in v1 but does nothing until a brain needs it: a new brain has an empty map
    and no gate rules of its own. The one exception is deliberate: the shipped gate rules on the
    meta skills' own files apply from day one.
17. The map stays Mermaid inside Markdown, as both source brains have it, in a strict dialect
    (lowercase id = skill, capitalised id = anything else, ids shared across diagrams, a fixed set
    of classes), rather than a JSON source rendered to Mermaid. That keeps one file a person can
    read and edit, and the lint rejects what the dialect forbids.
18. The `brain-*` skills' tree is in a template-owned `_meta/ROUTING-META.md`, so updates can
    change it; the brain's own map is brain-owned. `routing sync` writes blocks only into the
    brain's own skills.
19. Routers are a pattern `brain-write-skill` writes, plus one generic rules engine
    (`_meta/brain route`), so no brain writes its own route script. Rules files carry their own
    test cases, checked on commit.
20. The gate is Python standard library (the source used `jq`), lets a write through with a
    warning if the gate itself errors, and logs waivers in the brain's ignored `.brain/` rather
    than under `~/.claude`.
21. Left behind from the source brains' routing: exceptions for one-line header edits, waiver
    labels for who armed them, opt-in packs, and any fixed layout for work records.
