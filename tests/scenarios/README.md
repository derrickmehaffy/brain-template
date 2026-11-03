# Skill scenarios

`lint` proves only a skill's shape. Each file here runs one skill once, as a real headless Claude
Code session started inside a throwaway brain, and says what a pass looks like. Re-run a scenario
when its skill changes materially. There is no variance check: one run per change.

| File | Skill under test |
| --- | --- |
| `brain-write-skill.md` | `brain-write-skill`: a new skill, placed and linted |
| `router-fan-out.md` | `brain-write-skill`: a router for three skills behind one entry |
| `gate-refusal.md` | the skill gate, then `brain-write-skill`, never a waiver |
| `brain-write-script.md` | `brain-write-script` |
| `brain-write-practice.md` | `brain-write-practice` |
| `brain-retro.md` | `brain-retro`, handing to `brain-upstream` |
| `brain-upstream.md` | `brain-upstream` |
| `brain-sync.md` | `brain-sync` |
| `brain-setup.md` | `brain-setup`, the copy route |
| `template-make-brain.md` | `template-make-brain` |
| `template-intake.md` | `template-intake` |

Each file has the same three sections:

- `## Setup`: shell commands that build the scenario's folders, using the helpers below. Everything
  goes under `$SCEN`, a fresh temporary folder whose path holds a space; nothing touches a checkout.
- `## Prompt`: the words given to the session, which never name the skill. `Replies` lists what to
  answer when the session stops to ask something, in order; send a reply only when the turn ended on
  a question, and send nothing the session did not ask for.
- `## Pass when`: checkable items, judged from the transcript and the files the session left.

Results go in `RESULTS.md` next to this file (ignored by git): one row per scenario with pass or
fail, the date, the transcript's path, and what failed. A failure caused by a skill's instructions
is fixed through `brain-write-skill` and the scenario re-run; a failure in the harness is recorded,
not worked around.

## Before you start

- `claude auth status` must report `"loggedIn": true`: the scenarios run the CLI on its own login.
- Run from an ordinary terminal. A shell opened inside another Claude Code session (the desktop
  app, an IDE extension) inherits that host's variables (`CLAUDECODE`, `CLAUDE_CODE_*`,
  `ANTHROPIC_BASE_URL`): a `claude -p` started there expects the host to refresh its login and
  stops with "OAuth session expired and could not be refreshed", and `CLAUDE_CODE_SIMPLE=1` would
  turn on bare mode, which skips hooks and `CLAUDE.md`. Unset them, or use a plain terminal.
- The session loads the brain's `.claude/skills`, `.claude/settings.json` (the gate hooks) and
  `CLAUDE.md` because it starts in the brain root. Globally installed skills and hooks load too, on
  purpose: a scenario passes only when the `brain-*` skill fired rather than a lookalike.

## Helpers

Paste into the shell before a scenario's Setup, with `TEMPLATE` set to the checkout under test:

```bash
TEMPLATE="<path to the template checkout>"
SCEN="$(mktemp -d)/with space"; mkdir -p "$SCEN"
TODAY="$(date +%Y-%m-%d)"

# A committed git copy of the template's tracked and untracked-not-ignored files, with the
# pre-commit hook; `nolocal` leaves out local/ (a copy never set up), otherwise it is the
# template's own checkout.
copy_template() {
  mkdir -p "$1"
  git -C "$TEMPLATE" ls-files -co --exclude-standard -z \
    | tar -C "$TEMPLATE" --null -T - -cf - | tar -C "$1" -xf -
  git -C "$1" init -q && git -C "$1" symbolic-ref HEAD refs/heads/main
  git -C "$1" add -A && git -C "$1" commit -q -m "template copy for scenarios"
  "$1/_meta/brain" hook install >/dev/null
  [ "${2:-}" = nolocal ] || mkdir -p "$1/local"
}

# A homelab brain (prefix lab) made by `new` from a template copy.
make_brain() {
  "$1/_meta/brain" new "$2" --name "Homelab" --prefix lab \
    --description "Running and fixing the home network, its servers and their backups" >/dev/null
}

# A hand-written skill, its body on stdin: add_skill BRAIN NAME "DESCRIPTION" <<'EOF' … EOF
add_skill() {
  mkdir -p "$1/.claude/skills/$2"
  { printf -- '---\nname: %s\ndescription: "%s"\n---\n\n' "$2" "$3"; cat; } > "$1/.claude/skills/$2/SKILL.md"
}

# Insert a section into docs/ROUTING.md above `## Not drawn`, from stdin: add_diagram BRAIN <<'EOF' … EOF
add_diagram() {
  python3 -c 'import sys; p = sys.argv[1]; t = open(p, encoding="utf-8").read()
open(p, "w", encoding="utf-8").write(t.replace("## Not drawn", sys.stdin.read() + "\n## Not drawn", 1))' \
    "$1/docs/ROUTING.md"
}

# One turn: run_turn ROOT TRANSCRIPT "PROMPT" [SESSION_ID]. The first turn prints a new session id;
# pass it back to send a reply into the same session.
run_turn() {
  local sid="${4:-}" resume=()
  if [ -n "$sid" ]; then resume=(--resume "$sid"); else
    sid="$(python3 -c 'import uuid; print(uuid.uuid4())')"; resume=(--session-id "$sid"); fi
  echo "session: $sid"
  (cd "$1" && timeout "${TURN_LIMIT:-1200}" claude -p "$3" "${resume[@]}" \
     --output-format stream-json --verbose --permission-mode acceptEdits \
     --allowedTools Skill Read Glob Grep Edit Write \
       "Bash(_meta/brain *)" "Bash(./_meta/brain *)" "Bash(*/_meta/brain *)" \
       "Bash(git *)" "Bash(python3 *)" < /dev/null >> "$2")
}
```

A turn gets 20 minutes (`TURN_LIMIT`, in seconds, changes it). `timeout` is `gtimeout` on macOS
with coreutils; drop it if neither is there and watch the clock.

## Reading a transcript

The transcript is one JSON event per line. The tool calls, in order, with any refusal under them:

```bash
python3 - "$T" <<'EOF'
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    e = json.loads(line)
    body = e.get("message", {}).get("content")
    if not isinstance(body, list):
        continue
    for c in body:
        if c.get("type") == "tool_use":
            print(c["name"], json.dumps(c["input"])[:200])
        elif c.get("type") == "tool_result" and c.get("is_error"):
            print("   refused:", str(c.get("content"))[:200])
EOF
```

- **The skill fired**: a `tool_use` named `Skill` whose `skill` input is the skill under test.
- **No lookalike**: no `Skill` call to another skill that does the same job (a skill-writing,
  script-writing, practice-writing, retro, sync or setup skill from a plugin or another brain). A
  `Skill` call to a different `brain-*` skill the skill under test hands to is fine.
- **The gate refused**: a `tool_result` with `is_error` whose text holds `skill gate:` and names
  the skill to run.
- **A command ran**: a `Bash` `tool_use` whose `command` holds it.
