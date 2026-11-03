# Scenario: brain-sync

After the work in the other scenarios, the brain holds uncommitted changes of four kinds, and the
person says to commit. The setup stands in for "after the above" by writing those changes directly:
a new skill with its map node, a practice with its index, a retro row and an upstream suggestion.
The brain has a remote, so a push would show.

## Setup

````bash
copy_template "$SCEN/template"
make_brain "$SCEN/template" "$SCEN/brain"
ROOT="$SCEN/brain"; T="$SCEN/transcript.jsonl"

git clone -q --bare "$ROOT" "$SCEN/remote.git"
git -C "$ROOT" remote add origin "$SCEN/remote.git"
git -C "$ROOT" fetch -q origin && git -C "$ROOT" branch -q -u origin/main main
REMOTE_BEFORE="$(git -C "$SCEN/remote.git" rev-parse main)"

# 1. A skill and its node in the map.
add_skill "$ROOT" lab-check-backups "Check that last night's backup jobs ran and that one file restores from each, and say which did not. Use when asked whether the backups are fine, after a host was rebuilt, or before a restore. Does NOT change a backup job, and does NOT record why a job failed, which is brain-write-practice." <<'SKILL'
# Check the backups

A backup nobody has restored from is a hope. This reads each job's last run, restores one small
file from it, and changes nothing.

## Where this sits

**Call it directly when:** someone asks whether last night's backups are fine; nothing runs first.

## Sequence

1. **List the jobs** and when each last finished; one with no run since yesterday has failed.
2. **Restore one small file** from each job's latest snapshot into a temporary folder and compare it.
3. **Report** one line per job: ran or not, restored or not.

## Done when

- Every job has a line saying whether it ran and whether one file restored from it.
SKILL
add_diagram "$ROOT" <<'MAP'
## Homelab checks

```mermaid
flowchart LR
  LAB_CHECK(are the backups fine):::entry --> lab-check-backups:::work
```
MAP
(cd "$ROOT" && _meta/brain routing sync >/dev/null)

# 2. A practice and its regenerated index.
cat > "$ROOT/docs/practices/router-drops-mdns-across-vlans.md" <<PRACTICE
---
id: router-drops-mdns-across-vlans
tags: [network, mdns, vlan]
durability: volatile
evidence: researched
verified: $TODAY
source: the router's manual, multicast section
recheck: the router's current firmware release notes, multicast section
reviewed-against: []
---
The router does not forward mDNS between VLANs.

A device on one VLAN cannot discover a service announced on another by name alone. Reach it by
address, or turn on the router's mDNS reflector if the firmware has one.
PRACTICE
(cd "$ROOT" && _meta/brain practices index >/dev/null)

# 3. A retro row.
printf '| %s | brain-write-script | Put count_large_files.py straight in scripts/ instead of a folder for the system it touches | An upstream suggestion for brain-write-script step 3 (brain-upstream) | open |\n' \
  "$TODAY" >> "$ROOT/docs/RETRO-LOG.md"

# 4. An upstream suggestion.
VERSION="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["template"]["version"])' "$ROOT/brain.json")"
cat >> "$ROOT/docs/UPSTREAM.md" <<ENTRY

## $TODAY-script-folder-per-system
- template: $VERSION
- files: .claude/skills/brain-write-script/SKILL.md
- status: open
### What happened
A script that reads the file system was written straight into scripts/, with no folder for its system.
### Proposed change
Make step 3 refuse a script directly under scripts/, with the reason: the folder is how the next session finds it.
ENTRY

(cd "$ROOT" && _meta/brain lint && _meta/brain practices lint && git status --short)
````

## Prompt

```text
commit this
```

Replies, in order, each only when the turn ended on a question:

1. `Yes, commit them like that.`

Answer a question about pushing with `No, don't push.`

## Pass when

- The transcript has a `Skill` call for `brain-sync`, and none for a lookalike (another brain's
  sync or commit skill, a plugin's commit command).
- Before the first commit, `Bash` calls ran `_meta/brain lint`, `_meta/brain routing sync --check`,
  `_meta/brain practices lint` and `_meta/brain doctor --quick`.
- The new commits (`git log --name-only "$REMOTE_BEFORE"..main`) each hold one scope, with a subject
  starting with it: `skill(lab-check-backups): …` with the skill folder and `docs/ROUTING.md`;
  `practice(router-drops-mdns-across-vlans): …` with the entry and `docs/practices/INDEX.md`;
  `docs(retro): …` with `docs/RETRO-LOG.md`; `docs(upstream): …` with `docs/UPSTREAM.md`.
- Staging was by path: no `git add -A`, `git add .`, `git add -f` or `--no-verify` in any command.
- No `git push` ran, and `git -C "$SCEN/remote.git" rev-parse main` still equals `$REMOTE_BEFORE`.
- `git status --short` is empty afterwards.
