# Scenario: template-intake

A brain made from this template recorded one upstream suggestion. In the template's own checkout,
the person asks for the brains' suggestions to be checked. The brain must come out untouched.

## Setup

```bash
copy_template "$SCEN/template"
make_brain "$SCEN/template" "$SCEN/brain"          # `new` lists it in local/brains.txt
ROOT="$SCEN/template"; T="$SCEN/transcript.jsonl"
BRAIN="$SCEN/brain"

VERSION="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["template"]["version"])' "$BRAIN/brain.json")"
cat >> "$BRAIN/docs/UPSTREAM.md" <<ENTRY

## $TODAY-env-sync-for-every-variable
- template: $VERSION
- files: .claude/skills/brain-write-script/SKILL.md
- status: open
### What happened
A script took a private endpoint from the environment, as step 4 says, but step 4 asks for
\`env-sync --add\` only for a new secret. The variable never reached \`.env.example\`, so the next
machine had no idea the script needed it.
### Proposed change
In step 4, say to run \`_meta/brain env-sync --add KEY\` for every new variable a script reads from
the environment, secret or not.
ENTRY
(cd "$BRAIN" && git add docs/UPSTREAM.md && git commit -q -m "docs(upstream): ask for env-sync on every new variable")

snapshot() {  # every file under a folder, .git included: path, size, mtime
  python3 -c 'import json, os, sys
top = sys.argv[1]; out = {}
for d, _, fs in os.walk(top):
    for f in fs:
        p = os.path.join(d, f); st = os.lstat(p)
        out[os.path.relpath(p, top)] = [st.st_size, st.st_mtime_ns]
json.dump(out, sys.stdout, sort_keys=True)' "$1"
}
snapshot "$BRAIN" > "$SCEN/brain-before.json"
```

## Prompt

```text
check my brains for suggestions
```

The template's suite takes several minutes, and the session runs it: give the turns
`TURN_LIMIT=2400`.

Replies, in order, each only when the turn ended on a question:

1. `Accept it.`
2. `Yes, go ahead.`

## Pass when

- The transcript has a `Skill` call for `template-intake`, then one for `brain-write-skill` before
  the skill file changed; none for a lookalike (a plugin's feedback triage or skill editor).
- `_meta/brain upstream list` ran, and the session read the entry from the brain's
  `docs/UPSTREAM.md`, recommended accept or decline, and waited for `Accept it.` before changing
  anything.
- `.claude/skills/brain-write-script/SKILL.md` in the template copy asks for `env-sync --add` for
  every new variable; its body is at most 110 lines; `_meta/brain lint` ends
  `lint: 0 broken, 0 gap, 0 orphan` and `_meta/brain routing sync --check` passes, in the copy.
- `_meta/VERSION` moved from the version above to the next patch (`0.1.0` → `0.1.1`), and
  `_meta/CHANGELOG.md` has a `## <that version> — <today>` heading above the old one with
  `- landed: <the id> — <one line>`.
- The full suite passes in the copy
  (`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t .`), and the transcript shows
  the session ran it.
- `_meta/brain upstream list` in the copy now shows the id with its answer.
- The brain is untouched: `snapshot "$BRAIN"` equals `$SCEN/brain-before.json`.
- No brain detail (its name, its paths) reached a tracked file in the copy.
