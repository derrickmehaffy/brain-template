# Brain template

A **brain** is a folder you start Claude Code sessions in, whose root is a git repo holding what
Claude needs to do one kind of work well: skills, the rules that bite, what has been learned, and
small scripts. The project repos and large files the work produces sit inside the same folder but
are not part of the brain: the brain's `.gitignore` is an allowlist, so a nested repo, a generated
asset or a `.env` is never staged by accident.

This template is the starting point for every brain. A new brain has no domain skills at all. It
grows through seven **meta skills** that write skills, scripts and facts the same way every time,
and it can pull later improvements from the template without merge conflicts, because `update`
replaces only the files the template owns and refuses, rather than merges, when one was edited.

Requirements: Python 3.9+ (standard library only, no packages) and `git`, on Linux or macOS.

## Setting up a brain

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

Open Claude Code **at the brain's root**. The `.env` deny and the skill gate are read from
`.claude/settings.json` there, and only there. A session started in a plain subfolder should still
find the brain's skills, but one started inside a nested project repo likely will not, and gets
neither the deny nor the gate. Start it with `claude --add-dir <brain>` to load the brain's skills; the deny and the
gate still need a session started at the root.

## Keeping a brain current

`_meta/brain update` pulls the template's **committed** history (never its working tree, so
uncommitted template edits do not reach a brain) and replaces the files the template owns: `_meta/`,
the `brain-*` skills, and the managed blocks in `CLAUDE.md` and `.gitignore`. It also refreshes the
template's gate and `.env` entries in `.claude/settings.json` and the version in `brain.json`; every
other entry is left alone, and so is everything else in the brain. It refuses, rather than merges,
when a template-owned file was edited in the brain; it prints the changelog entries it brings and
does not commit, `brain-sync` does.

## Sending a change upstream

A brain never edits a template-owned file, and the template never writes into a brain. They exchange
suggestions by reading each other:

1. In the brain, `brain-upstream` records one proposed change in `docs/UPSTREAM.md`, written so it
   holds nothing private to that brain.
2. In the template, `template-intake` reads the open suggestions from the brains listed in
   `local/brains.txt`, accepts or declines each with the person, makes an accepted change with its
   tests, and answers every one in `_meta/CHANGELOG.md` by id. Committing is enough; there is no
   release step.
3. In the brain, the next `update` reports the answered ids, and `brain-sync` marks each one landed
   or declined.

## The skills

Seven meta skills ship in every brain:

| Skill | One line |
| --- | --- |
| `brain-write-skill` | Create, change, split or rename one of the brain's skills, starting from where it sits in the routing map; write a router when an entry point fans out; gate output that must not be improvised. |
| `brain-write-script` | Decide whether code earns a file, place it by the system it touches, keep it read-only unless its name says otherwise, and record what the system can and cannot do. |
| `brain-write-practice` | Record one verified fact with its evidence and how to re-check it, after ruling out a duplicate. |
| `brain-retro` | When a skill went wrong or work fit no skill: log it and propose the one change that fixes it. |
| `brain-upstream` | Record a proposed change to a template-owned file for the template to take in. |
| `brain-sync` | Run the checks, commit with a scoped subject, pull with rebase, push when asked. |
| `brain-setup` | Turn a copy of the template into a brain; in a brain, explain it, repair what `doctor` reports and run `update`. |

Two skills work on the template itself and are never copied into a brain:

| Skill | One line |
| --- | --- |
| `template-make-brain` | Create a brain with `new`, or adopt a folder with `adopt`, after the setup questions and a dry run. |
| `template-intake` | Take in the upstream suggestions brains have recorded, with the person, and answer each in the changelog. |

## Forced routing and the skill gate

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

## The privacy guard

A pre-commit hook, installed by `new`, `adopt` and `init`, blocks a commit that stages:

- a `.env` file (other than `.env.example`);
- a credential shape: a private key header, a common token prefix, `password=` followed by a value;
- a private term from `.brain-private` (ignored; one regular expression per line, matched
  case-insensitively, and an invalid one is a BLOCK: hostnames, unreleased project names), or a
  match of the `deny_patterns` in `brain.json`;
- a file over `max_file_kb` that is not in `large_file_allow`;
- a path inside a nested git repo.

Findings name the rule, file and line, never the value. A template file exactly as shipped (it
matches `_meta/MANIFEST.sha256`) is exempt from the private-term and deny-pattern scan, since the
person cannot edit it and template text should not block every commit; credential shapes and file
names are still checked, and an edited template file is scanned like any other.

## Working on the template

`CLAUDE.md` here is for sessions that work on the template. Run the tests before committing:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . -v
```

The design is in `docs/superpowers/specs/`.
