# Doctor lines and their fixes

Fix every BLOCK; offer a fix for each WARN in plain words and make it on a yes. Then run `doctor` again.

| Doctor line | Fix |
| --- | --- |
| `git`, `python3` or `scripts.python` missing (BLOCK) | Step 0, or point `brain.json` `scripts.python` at an interpreter that exists |
| `brain.json` invalid, or no prefix (BLOCK) | Fix the file as the line says |
| A copy of the template not set up yet (BLOCK) | The copy route |
| A template-only file in a brain, e.g. a `template-*` skill (BLOCK) | It came with a copy and never ships: `git rm -r` it, on a yes |
| A template-owned file differs from the manifest (WARN) | A local edit: `brain-upstream` records it, then restores it |
| Template version behind its source (WARN) | The update in the skill |
| Pre-commit hook missing (BLOCK) | `_meta/brain hook install` |
| `core.hooksPath` bypasses the hook (BLOCK) | `git config --show-origin --get core.hooksPath`; unset it in this repo on a yes; if it is set globally, the person decides |
| Settings lack the `.env` deny, a gate hook or the session-start check (WARN) | The update rewrites those entries and leaves the file's others alone |
| Gate rules, or a router's `rules.json`, invalid or naming a missing skill | `brain-write-skill`; `_meta/brain route <router>/rules.json --check` shows the failing case |
| `.env` not mode 600, or keys in `.env.example` missing from `.env` (WARN) | `chmod 600 .env`; `_meta/brain env-sync --open` adds the missing keys and opens the file for the person to fill in. Never read or print a value |
| `lint` BROKEN (BLOCK) or GAPs (WARN) | `_meta/brain lint` lists them: the brain's own skills → `brain-write-skill`; a `brain-*` skill → `brain-upstream` |
| `practices lint` errors (BLOCK) or stale entries (WARN) | `brain-write-practice`, whose sweep handles stale entries |
| Script tests fail | `brain-write-script` |
| No online backup (WARN) | Ask once: "Online backup" in the skill, or `"backup": "local"` |
| Uncommitted or unpushed work (WARN) | `brain-sync` |
| A nested repo with no remote or unpushed commits (WARN) | Read them out: this is the work lost if the disk died. Offer to back each up; never stage them into the brain |
| A `docs/` folder missing from `docs/README.md` (WARN) | Add one line for it to `docs/README.md` |
| Open hand-offs in `docs/INBOX.md` (WARN) | Read them out and offer to start; when one is done, set its status to `done` (or `declined: <reason>`) and commit |
| A brain listed in `brain.json` `brains` is missing (WARN) | Ask where it went; fix the folder, or take it off the list |
| A tracked file over `max_file_kb` (WARN) | A project file: `git rm --cached` it, on a yes. If it belongs, add it to `privacy.large_file_allow` |
| `.brain-private` expected but missing (WARN) | A new computer: ask the person for their list again and write `.brain-private`; it is never committed |
