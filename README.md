<p align="center">
  <picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/banner-dark.svg"><img src="docs/images/banner.svg" width="100%" alt="Brain template for Claude Code. Teach Claude once. It remembers how."></picture>
</p>

<p align="center">
  <a href="https://github.com/derrickmehaffy/brain-template/actions/workflows/tests.yml"><img src="https://github.com/derrickmehaffy/brain-template/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-3776AB.svg" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-none-2B7A74.svg" alt="No dependencies">
</p>

<p align="center">
  <a href="https://github.com/derrickmehaffy/brain-template/generate"><b>Use this template</b></a> ·
  <a href="docs/guides/start-here.md"><b>Start here</b> (no git needed)</a> ·
  <a href="docs/guides/prompts.md">Things to say</a> ·
  <a href="#reference">Reference</a>
</p>

Claude Code is sharp within a session and starts from zero in the next one. A **brain** fixes that.
It is a folder you open Claude in, holding what Claude needs to do one kind of work well: the
routines it follows, the facts it has checked, the words you use and the small scripts it runs.
Every session starts from all of it, and every change is saved in git, so nothing learned is lost
and anything can be undone.

Make one for a home server, a game mod, a customer inbox, a research project: anything you do with
Claude again and again. A new brain starts with no routines of its own, just seven meta skills
that write the rest the same way every time.

## Why a brain

- 🧠 **It remembers.** Routines become skills, checked facts become practices, and your words go
  in a glossary. Every session starts from all of it.
- 🧭 **It picks the right routine.** One routing map says which skill handles what, so the work
  is never improvised from memory.
- 🚦 **It checks itself.** The skill gate refuses a skill's output until that skill really ran,
  and every chat opens with a health check that names anything needing attention.
- 🔒 **It keeps secrets out.** A pre-commit guard blocks `.env` files, credentials and the names
  you mark private. Keys stay in `.env` (or 1Password) and are never printed.
- 🔁 **It gets better.** When something goes wrong, a retro proposes the one change that fixes
  it, and `update` brings in the template's improvements without merge conflicts.
- 📦 **Nothing to install.** Python 3.9+ and git. No packages, no server, no extra account.

## How it works

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/how-it-works-dark.svg"><img src="docs/images/how-it-works.svg" width="100%" alt="A loop of five steps: ask in your own words; the routing map picks the skill; the skill runs and the gate checks it did; the work is checked and committed with no secrets in it; a retro fixes the skill and a practice keeps the fact. The next session starts from all of it."></picture></p>

You talk to Claude the way you normally would. The brain's `CLAUDE.md` and routing map steer each
request to the skill written for it, the skill gate makes sure that skill actually runs, and
`brain-sync` saves the result through the privacy guard. When something goes wrong, `brain-retro`
turns it into a fix, so the same mistake does not happen twice.

## Get started

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/getting-started-dark.svg"><img src="docs/images/getting-started.svg" width="100%" alt="Three steps: get your copy with Use this template and Private; open the folder in Claude Code; say what the brain is for, and Claude checks the computer, asks a few plain questions, rehearses and sets it up."></picture></p>

1. **Get your copy.** Click **[Use this template](https://github.com/derrickmehaffy/brain-template/generate)**, then **Create a new
   repository**, and choose **Private**. Or ask Claude to download the template for you.
2. **Open it in Claude Code.** In the desktop app's Code tab, open the folder. In a terminal, run
   `claude` there.
3. **Say "Set this up as a brain for &lt;what you do&gt;."** Claude checks the computer, asks a few
   plain questions, shows a rehearsal of what it will do, and sets the brain up when you say yes.

> [!NOTE]
> **Your copy becomes yours.** Setup removes everything that is only there for developing the
> template: this README, the guides and images, the tests, and the GitHub files (licence, issue
> forms, CI). What is left is a clean brain with a README of its own. The licence for the harness
> and the `brain-*` skills travels in `_meta/LICENSE`.

**Never used git or a terminal?** [Start here](docs/guides/start-here.md) walks through every click,
and Claude does the technical parts. You need macOS or Linux (on Windows, inside WSL), Claude Code,
Python 3.9+ and git; Claude checks for the last two and helps install them.

## Things to say

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/things-to-say-dark.svg"><img src="docs/images/things-to-say.svg" width="100%" alt="Seven things to say and what each does: what's in this brain (explains it and runs the health check); make it a routine (writes a skill); remember what we found (records a practice); that went wrong (runs a retro); keep that query as a script (writes a script); save this (checks and commits); update this brain from the template."></picture></p>

Say it in your own words: the skill descriptions and the routing map find the right skill. More, by
step and by kind of work, in [docs/guides/prompts.md](docs/guides/prompts.md).

## What's inside a brain

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/whats-inside-dark.svg"><img src="docs/images/whats-inside.svg" width="100%" alt="The folder of a brain called my-homelab. Yours: CLAUDE.md, README.md, your lab-* skills, docs with the routing map, practices and glossary, and scripts. From the template: the seven brain-* skills and _meta, the harness. In the folder but never saved: .env and your project repos and big files."></picture></p>

The projects, big files and keys the work produces live in the same folder but are never part of the
brain. Its `.gitignore` is an allowlist, so a nested repo, a generated asset or a `.env` is never
staged by accident.

## One template, many brains

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/template-and-brains-dark.svg"><img src="docs/images/template-and-brains.svg" width="100%" alt="The brain template above three brains, my-homelab, my-game-mod and shop-inbox. Update brings fixes and features down without touching a brain's own files; brain-upstream sends a suggestion up, with nothing private in it, answered in the changelog."></picture></p>

Make one brain per kind of work. Every brain pulls the template's fixes with `update`, and sends
ideas back with `brain-upstream`; neither side ever writes into the other.

## Reference

The detail behind everything above.

### What a brain is, exactly

A **brain** is a folder you start Claude Code sessions in, whose root is a git repo holding what
Claude needs to do one kind of work well: skills, the rules that bite, what has been learned, and
small scripts. The project repos and large files the work produces sit inside the same folder but
are not part of the brain: the brain's `.gitignore` is an allowlist, so a nested repo, a generated
asset or a `.env` is never staged by accident.

This template is the starting point for every brain. A new brain has no domain skills at all. It
grows through seven **meta skills** that write skills, scripts and facts the same way every time,
and it can pull later improvements from the template without merge conflicts, because `update`
replaces only the files the template owns and refuses, rather than merges, when one was edited.

Requirements: Python 3.9+ (standard library only, no packages) and `git`, on macOS or Linux (on
Windows, inside WSL).

### Setting up a brain

New to this? [docs/guides/making-a-brain.md](docs/guides/making-a-brain.md) covers what a brain is
for and how it grows, and [docs/guides/prompts.md](docs/guides/prompts.md) has what to say to Claude
at each step, with starting points for common kinds of work.

There are three ways in. All end in the same state: the first commit made, the pre-commit guard
installed, `_meta/brain doctor` with nothing blocking, and none of the template's own files present.
(`doctor` is the read-only health check: one `ok`, `WARN` or `BLOCK` line per check, exit 1 if
anything blocks.) Each runs with `--dry-run` first, and the skill shows the result before anything is
written.

| Starting from | Say | Skill and command |
| --- | --- | --- |
| A session in the template | "make a brain for X at `<path>`" | `template-make-brain` runs `_meta/brain new <dir> --name N --prefix P` |
| A session in the template | "turn `<folder>` into a brain" | `template-make-brain` runs `_meta/brain adopt <dir> --name N --prefix P` |
| A session in a copy of the template (git clone, GitHub "Use this template", a copied folder) | "set this up" | `brain-setup` runs `_meta/brain init --name N --prefix P` |

Setup asks four things: the name, the prefix for the brain's own skills (`lab` gives `lab-*`), a
one-line description, and anything that must never be committed (kept in `.brain-private`, which is
ignored). Everything else takes the defaults in `brain.json`.

- `new` builds the whole brain, first commit included, in a temporary folder beside the target and
  moves it into place only when that succeeded, so a failed `new` leaves nothing behind.
  `--dry-run` rehearses the real build and discards it.
- `adopt` never moves, renames, overwrites or deletes a file already in the folder. It prints an
  inventory (nested repos at any depth, large folders, existing skills, `CLAUDE.md`, `.env`), adds
  the brain files and the managed blocks (marked regions at the top of `CLAUDE.md` and `.gitignore`
  that the template owns and refreshes, with the brain's own lines below), and stops before
  committing. It shows what `git add -A`
  would stage, with a BLOCK or WARN line for anything that needs a decision (an embedded repo, a
  tracked `.env`); the first commit is made once those are resolved and the person says yes.
- `init` refuses anything but an unchanged copy of the template (and refuses where a `local/`
  folder exists, which is how it never converts the template itself). A plain clone gets a fresh
  history, only when every commit is on its remote. A clone of a local checkout tracks the
  template's canonical source and keeps the local path in `brain.local.json`, which is ignored.
  Before publishing the template, set `template.source` in its `brain.json` to the published URL, so
  `init` in a clone of it starts a fresh history and never keeps the template as `origin`.

Open Claude Code **at the brain's root**. The `.env` deny, the skill gate and the brain's MCP servers
are read from `.claude/settings.json` and `.mcp.json` there, and only there. Each session starts with
`_meta/brain doctor --brief`, a hook that prints only what needs attention, so a brain that is behind
its template or has unpushed work says so before the work begins. A session started inside a
nested project repo gets neither the deny nor the gate, and likely not the brain's skills either, so
start every session at the root. (In a terminal, `claude --add-dir <brain>` from a project folder
loads the brain's skills, but still not the deny or the gate.)

### Keeping a brain current

`_meta/brain update` pulls the template's **committed** history (never its working tree, so
uncommitted template edits do not reach a brain) and replaces the files the template owns: `_meta/`,
the `brain-*` skills, and the managed blocks in `CLAUDE.md` and `.gitignore`. It also refreshes the
template's gate and `.env` entries in `.claude/settings.json` and the version in `brain.json`; every
other entry is left alone, and so is everything else in the brain. It refuses, rather than merges,
when a template-owned file was edited in the brain; it prints the changelog entries it brings and
does not commit, `brain-sync` does.

### Sending a change upstream

A brain never edits a template-owned file, and the template never writes into a brain. They exchange
suggestions by reading each other:

1. In the brain, `brain-upstream` records one proposed change in `docs/UPSTREAM.md`, written so it
   holds nothing private to that brain.
2. In the template, `template-intake` reads the open suggestions from the brains listed in
   `local/brains.txt`, accepts or declines each with the person, makes an accepted change, and
   answers every one in `_meta/CHANGELOG.md` by id. Committing is enough; there is no
   release step.
3. In the brain, the next `update` reports the answered ids, and `brain-sync` marks each one landed
   or declined.

### The skills

Seven meta skills ship in every brain:

| Skill | One line |
| --- | --- |
| `brain-write-skill` | Create, change, split or rename one of the brain's skills, starting from where it sits in the routing map; write a router when an entry point fans out; gate output that must not be improvised; write the report-only agents a skill dispatches. |
| `brain-write-script` | Decide whether code earns a file, place it by the system it touches, keep it read-only unless its name says otherwise, and record what the system can and cannot do; connect a system's MCP server in `.mcp.json`. |
| `brain-write-practice` | Record one verified fact with its evidence and how to re-check it, after ruling out a duplicate; add a term that misled to the glossary. |
| `brain-retro` | When a skill went wrong or work fit no skill: log it and propose the one change that fixes it; review which skills go unused (`_meta/brain usage`). |
| `brain-upstream` | Record a proposed change to a template-owned file for the template to take in. |
| `brain-sync` | Run the checks, commit with a scoped subject, pull with rebase, push when asked. |
| `brain-setup` | Turn a copy of the template into a brain; in a brain, explain it, repair what `doctor` reports and run `update`. |

Two skills work on the template itself and are never copied into a brain:

| Skill | One line |
| --- | --- |
| `template-make-brain` | Create a brain with `new`, or adopt a folder with `adopt`, after the setup questions and a dry run. |
| `template-intake` | Take in the upstream suggestions brains have recorded, with the person, and answer each in the changelog. |

### Forced routing and the skill gate

Routing is forced, not left to judgement. One map says which skill hands to which and every skill is
in it: a brain's own skills in `docs/ROUTING.md`, the `brain-*` skills in `_meta/ROUTING-META.md`.
A router fans an entry point out to three or more skills by rule (`_meta/brain route`), never by
reading, and `_meta/brain lint` rejects a map that breaks the rules.

**Every brain gets a skill gate.** Reading a skill is not running it, and a skill imitated from memory
skips its `references/`. The gate is a hook, wired in `.claude/settings.json`: a skill's output can
only be written after that skill ran in the session. A skill file is refused until `brain-write-skill`
has run, a script until `brain-write-script` has, and so on; a brain adds rules for its own skills.
The refusal names the skill to invoke. A one-time waiver exists (`_meta/brain gate waive`), and only
on the person's say-so. The gate is friction and visibility, not a security boundary.

### Secrets, MCP servers, agents and the glossary

- **Secrets** live in `.env`, which git ignores and Claude is denied reading. A value can be the
  secret or a 1Password reference (`op://vault/item/field`, read with `op read` when needed). Names
  go in with `_meta/brain env-sync --add KEY`. Scripts read secrets through their loader; anything
  else gets them through `_meta/brain secret run KEY[,KEY] COMMAND`, which puts them in that
  command's environment and never prints one itself (a command that prints its environment
  would, so never run one).
- **MCP servers** a brain needs go in its `.mcp.json`, not in user settings, where every session
  everywhere would load their tools. A server that needs a secret runs under `secret run`.
- **Agents** (`.claude/agents/<prefix>-*.md`) are helpers a skill dispatches: explicit tools, a
  model, and a report back rather than edits. `lint` checks each one.
- **The glossary** (`docs/GLOSSARY.md`) is loaded into every session: one line per term that means
  something specific here, with the words to avoid.
- **Skill usage**: the gate logs every skill run to `.brain/skill-usage.log`, and
  `_meta/brain usage` shows which skills earn their place.

### The privacy guard

A pre-commit hook, installed by `new`, `adopt` and `init`, blocks a commit that stages:

- a `.env` file (other than `.env.example`);
- a credential shape: a private key header, a common token prefix, `password=` followed by a value;
- a private term from `.brain-private` (ignored): one term per line, written as a person would say
  it (a hostname, an address, a client or project name), matched in any case as a whole word; a
  line starting `re:` is a regular expression instead, and an invalid one is a BLOCK. Or a match of
  the `deny_patterns` in `brain.json`;
- a file over `max_file_kb` that is not in `large_file_allow`;
- a path inside a nested git repo.

Findings name the rule, file and line, never the value. A template file exactly as shipped (it
matches `_meta/MANIFEST.sha256`) is exempt from the private-term and deny-pattern scan, since the
person cannot edit it and template text should not block every commit; credential shapes and file
names are still checked, and an edited template file is scanned like any other.

### Working on the template

`CLAUDE.md` here is for sessions that work on the template. Run the tests before committing:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . -v
```

The design is in `docs/superpowers/specs/`. [CONTRIBUTING.md](CONTRIBUTING.md) covers setting up a
checkout, the checks and how changes are proposed; report vulnerabilities as
[SECURITY.md](SECURITY.md) says, and see the [code of conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE). A brain made from the template carries the licence for the harness and the
`brain-*` skills in `_meta/LICENSE`; everything else in a brain is its owner's own.
