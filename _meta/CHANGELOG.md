# Changelog

## 0.1.0 — 2026-11-02

- Setup: `new` makes a brain from a template checkout, building it aside and moving it into place so a failed run leaves nothing; `adopt` turns an existing folder into one without moving or overwriting a file; `init` turns a copy of the template into one; each has `--dry-run`.
- Updates: `update` pulls the template's committed history into a brain, touching only template-owned files, with a hash manifest to detect local edits; `upstream list` shows a brain's suggestions and the changelog entries that answer them.
- Harness: one `_meta/brain` command in standard-library Python 3.9+, with `doctor` (read-only health check), `lint`, `rename-skill` and `env-sync` (`--add KEY`, `--list`).
- Routing: a strict Mermaid routing map, read from `docs/ROUTING.md` and `_meta/ROUTING-META.md` as one graph; `routing sync` and `routing show`; `route` applies a router's rules file.
- Skill gate: hooks that refuse a skill's output until that skill ran in the session, shipped rules on the meta skills' files, brain rules in `brain.json`, a one-shot waiver and `gate status`.
- Privacy guard: a pre-commit hook for `.env` files, credential shapes, private terms, deny patterns, large files and nested repos; `hook self-test` proves each rule blocks.
- Practices: a store of verified facts in `docs/practices/` with a linter, a generated index, candidate matching and search.
- Skills: seven `brain-*` meta skills (`brain-write-skill`, `brain-write-script`, `brain-write-practice`, `brain-retro`, `brain-upstream`, `brain-sync`, `brain-setup`); `template-make-brain` and `template-intake` stay in the template.
- Skeleton: starter `CLAUDE.md`, `README.md`, `.gitignore` allowlist, `.env.example`, `docs/` (routing map, capabilities, logs, upstream, practices) and `scripts/` for each new brain.
