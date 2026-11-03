# Commands

Every brain has one command, `_meta/brain`, in standard-library Python 3.9 or newer: no packages, on
macOS and Linux (on Windows, inside WSL). Claude runs these for you; they are listed here so you can
see what it is doing. `_meta/brain <command> --help` prints the full options of any of them.

Commands that change something have a rehearsal (`--dry-run`) or are a dry run unless told otherwise.
None of them prints a secret.

## Making and keeping a brain

| Command | What it does |
| --- | --- |
| `new DIR --name N --prefix P` | Make a brain in a new or empty folder, from this template checkout. Builds it beside the target and moves it into place only when everything worked. |
| `adopt DIR --name N --prefix P` | Turn a folder that already holds work into a brain. Never moves, renames, overwrites or deletes a file; stops before the first commit. |
| `init --name N --prefix P` | Turn a copy of the template (a clone, a download, "Use this template") into a brain, in place. `--keep-guides` keeps the template's guides and reference in `docs/`. |
| `update` | Pull the template's committed changes into this brain. Refuses, rather than merges, when you edited a file the template owns. `--from`, `--ref`, `--dry-run`. |
| `doctor` | The read-only health check: one `ok`, `WARN` or `BLOCK` line per check; exit 1 if anything blocks. `--quick` skips the slow checks; `--brief` is the session-start form. |

`new`, `adopt` and `init` all take `--description`, `--private TERM` (repeatable: a name that must
never be committed), `--python` and `--packages {stdlib-only,allowed}` for the brain's scripts, and
`--dry-run`. See [Setting up](setting-up.md).

## Every day

| Command | What it does |
| --- | --- |
| `lint` | Check the skills and the routing map: BROKEN blocks, GAP is a gap to explain, ORPHAN is an agent no skill names. |
| `routing show [SKILL]` | The map's entry points and isolated skills, or one skill's neighbours. |
| `routing sync [--check]` | Write each skill's "Where this sits" block from the map. |
| `route RULES [--set FIELD=VALUE] [--check]` | Apply a router's rules file and name one skill; `--check` runs its test cases. |
| `practices search TERMS` | Find checked facts that match every term. |
| `practices lint`, `index`, `candidates` | Check the store, rebuild its index, rank entries a new one may duplicate. |
| `usage [--days N]` | How often each skill ran here, and which never did. |
| `rename-skill OLD NEW [--apply]` | Rename a skill everywhere it is named; a dry run unless `--apply`. |

## Secrets

| Command | What it does |
| --- | --- |
| `env-sync` | Add the key names `.env.example` lists to `.env`. Never prints a value. |
| `env-sync --add KEY` | Add one key name to both files, and say where to fill it in. |
| `env-sync --open` | Open `.env` in your text editor, for you to paste values. |
| `env-sync --list` | Each key name as `set`, `empty` or `missing`; never a value. |
| `secret run KEY[,KEY] COMMAND` | Run a command with those secrets in its environment, read from `.env` (or 1Password for an `op://` value). Never prints one. |

## Safety rails

| Command | What it does |
| --- | --- |
| `gate status` | What ran this session, any waiver, the last refusal. |
| `gate waive SKILL REASON` | Let the next write that skill's rule refuses through, once. Only on the person's say-so. |
| `gate record`, `gate check` | The hooks themselves, fed by Claude Code. |
| `hook install` | Install the pre-commit privacy guard. |
| `hook self-test` | Prove every rule of the guard blocks. |
| `hook pre-commit` | The guard itself, run by git. |

## Mods

| Command | What it does |
| --- | --- |
| `mods list` | The brain's mods in `mods/`, each with its link and whether its kit copy is current. |
| `mods new NAME [--dry-run]` | Start `mods/<prefix>-NAME/` from the kit's starter, with the kit copied in and the link that loads it. |
| `mods sync [--check] [--dry-run]` | Put the kit back into every mod's `hooks/kit/`, or (`--check`) list the copies that differ. |
| `mods link [NAME…] [--dry-run]` | Make a missing `.claude/skills/<name>` link; never replaces anything else. |
| `mods check [NAME…]` | Run `claude plugin validate` and `claude plugin test` on each mod (needs the `claude` CLI). |
| `mods ready` | Whether this computer's Claude Code can draw mods; never fails. |

See [Building mods](../guides/building-mods.md).

## Several brains

| Command | What it does |
| --- | --- |
| `brains list` | The brains this one knows: name, folder, what each is for, open hand-offs. |
| `brains add FOLDER` | Check a folder is a brain, and add it to `brain.json` `brains`. |
| `brains handoff NAME --title T --body B` | Append an open entry to that brain's `docs/INBOX.md`. Writes nothing else there and never commits. |
| `upstream list` | Suggestions this brain recorded for the template, with their answers. |

See [Several brains](several-brains.md).
