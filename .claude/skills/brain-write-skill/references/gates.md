# Gating a skill's output

When a skill's output should be refused unless the skill actually ran, how to write the rule, and
how waivers work. `SKILL.md` step 6 says when to come here.

## What the gate does

Reading a skill is not running it. An agent that read a skill and imitates it from memory skips
everything in its `references/`, and no instruction reliably stops that, so the gate is a hook
instead. `.claude/settings.json` wires it (setup does this; `doctor` warns when it is missing):

- after every Skill tool call, `_meta/brain gate record` notes the skill against the session;
- before every Write, Edit and Bash call, `_meta/brain gate check` works out which files the call
  writes, and refuses one that a rule reserves for a skill that has not run in this session.

The refusal names the skill to invoke and the rule's `why`:

```text
skill gate: writing infra/hosts/nas.yml needs lab-change-config to run first in this session. Host config is applied to live machines; every revision goes back through lab-change-config's review. Invoke the skill; a one-time waiver needs the person's express say-so: _meta/brain gate waive lab-change-config "<reason, and who said so>"
```

## When to gate

Gate output that would cost something if improvised:

- **it leaves the brain**: a post, a PR or release text, a reply to someone, config applied to a
  live system;
- **a later step trusts it** without checking again: a reviewed draft another skill sends, a
  record a report is built from, a file a deploy reads.

Leave scratch files, notes and anything several skills write freely ungated. A rule lists every
skill allowed to write its path, and a path two rules match needs an owner of each to have run, so
a broad glob soon blocks honest work.

| Brain | Output | Rule path | Owning skill |
| --- | --- | --- | --- |
| homelab | host config that is applied to live machines | `infra/hosts/**` | `lab-change-config`, with `spend_on_revision` |
| plugin maintainer | release notes published with each tag | `plugins/*/CHANGELOG.md` | `plug-write-changelog` |
| game modding | the text of a mod's public listing | `mods/*/listing/**` | `mod-write-listing`, with `spend_on_revision` |

A gate only guards the path its rule names, so the skill's body must say exactly where it writes
that output. Output written "wherever" cannot be gated.

## The rule

In `brain.json`, a list under `gates`:

```json
"gates": [
  {
    "path": "infra/hosts/**",
    "skills": ["lab-change-config"],
    "spend_on_revision": true,
    "why": "Host config is applied to live machines; every revision goes back through lab-change-config's review."
  }
]
```

| Key | Meaning |
| --- | --- |
| `path` | A glob relative to the brain root; it may reach into project folders. `*` and `?` stay inside one path segment, `**` crosses segments (`a/**` is everything below `a/`, `**/x` is `x` anywhere), every other character is literal, and the glob must match the whole path. |
| `skills` | A non-empty list; a run of any one of them in this session satisfies the rule. |
| `spend_on_revision` | Optional, `false` by default; below. |
| `why` | One sentence: what goes wrong without the skill. It is printed in every refusal, so write it for the agent that hits it. |

Then run `_meta/brain lint` (BROKEN when the entry is malformed or names a skill that does not
exist) and `_meta/brain routing sync`, which adds a `**Reserved output:**` line naming the path to
the owning skill's block, so whoever reads the skill sees what it guards.

## spend_on_revision

- **Without it**, once the skill has run in a session, every write to the path passes for the rest
  of that session.
- **With it**, every write still needs a run, but creating a file does not use the run up, and each
  edit of an existing file does: the next edit needs the skill invoked again.

Use it when every revision must go back through the skill's review (config that is validated each
time, a reply that is re-checked each time it changes). Leave it off for files the skill edits many
times in one run, or each of those edits will need a fresh invocation.

## Seeing a rule bite without writing anything

Pipe a made-up Write call to the check, with a session id of its own:

```bash
printf '%s' '{"session_id":"probe","tool_name":"Write","tool_input":{"file_path":"infra/hosts/nas.yml"},"cwd":"'"$PWD"'"}' | _meta/brain gate check
```

A rule that matches prints the refusal as JSON (`"permissionDecision": "deny"`); a path no rule
covers prints nothing. Try one path the rule must cover and one it must not, since a `*` that was
meant to be `**` fails silently.

The probe is a real check, so it has side effects:

- Run it only when `_meta/brain gate status` shows no armed waiver. A probe the gate would refuse
  spends the waiver, and logs a `used` line, exactly as a real write would.
- A refused probe is recorded as the last refusal of session `probe`, which `gate status` then shows
  as the latest session. Read a particular session with `_meta/brain gate status --session <id>`.

## Shipped rules, gates_off, gate_exempt

The template ships rules on the meta skills' own files, in `_meta/gates.json`:

| Path | Owning skill |
| --- | --- |
| `.claude/skills/<prefix>-*/**`, `docs/ROUTING.md` | `brain-write-skill` |
| `scripts/**`, `docs/CAPABILITIES.md` | `brain-write-script` |
| `docs/practices/**` | `brain-write-practice` |
| `docs/RETRO-LOG.md`, `docs/UNCLASSIFIED-LOG.md` | `brain-retro` |
| `docs/UPSTREAM.md` | `brain-upstream`, `brain-sync` |

In the template, whose prefix is `template`, the first row also covers `.claude/skills/brain-*/**`.

To turn one off, which is the person's decision and rarely right, add it to `brain.json` with
their reason:

```json
"gates_off": [ { "path": "docs/CAPABILITIES.md", "why": "<the person's reason>" } ]
```

The path is the shipped rule's, as `_meta/gates.json` writes it (`.claude/skills/{prefix}-*/**`)
or expanded (`.claude/skills/lab-*/**`). An entry without a `why` is BROKEN.

`gate_exempt` lists globs no rule is checked against, for folders that hold history nobody revises:
`"gate_exempt": ["docs/archive/**"]`.

## The waiver

The answer to a refusal is to invoke the skill it names. A waiver is for the rare write the person
wants through without it, and it is theirs to give:

- **Only on the person's express say-so, in this conversation, for this write.** Never on your own
  initiative, never because the refusal shows the command, never in advance, never because an
  earlier waiver was given.
- The reason says why and who said so:
  `_meta/brain gate waive lab-change-config "the resolver is down; the person said to skip the review this once"`.
- It is one-shot: the next write the gate would refuse for that skill goes through, the use is
  announced as a system message and logged to `.brain/gate-waivers.log`, and the waiver is gone.
  Arming a new one replaces one that was never used.
- The waiver file and its log are refused to every tool call; only `gate waive` writes them.

`_meta/brain gate status` prints the latest session's id, what ran in it, any armed waiver and the
last refusal. Use it when a refusal is a surprise: the skill most often ran in another session.

## What the gate is not

- **Not a security boundary.** Anything with a shell can get round it; the point is that doing so
  is deliberate, single-use and visible.
- **Not a review.** It knows that a skill ran in this session, not that its steps were followed or
  that the output is right. The checks and a real run cover that.
- **Not complete.** It sees Write and Edit, and the usual shell writes: redirections, `tee`, `cp`,
  `mv`, `sed -i`. Known gaps, where a write to a ruled path goes through unseen:
  - a target held in a variable or a substitution (`$VAR`, `${...}`, `$(...)`), since the gate reads
    the command's text and never runs it;
  - a command passed as a string to `bash -c` or `eval`;
  - a program that opens the file itself: python, `perl -pi`, `sed` run from a script;
  - any other program that writes a file is not recognised (for example `dd of=`, `rsync`,
    `curl -o`, `patch`, `truncate`, `touch`, `install`, `xargs`, `find -exec`, `git checkout --`,
    `sh -c`): only the writers named above are;
  - `cd X && ...`: the gate does not follow the `cd`, so a relative target is read against the
    folder the session started in;
  - `exec 3<> file`, which opens the file for writing on a descriptor;
  - a backtick substitution inside double quotes;
  - case-insensitive filesystems: a rule's path matches case-sensitively, so `Docs/Practices/x.md`
    is not `docs/practices/x.md` to the gate while the disk treats them as one;
  - run-state forgery: which skills ran is kept in `$XDG_RUNTIME_DIR/brain-gate` when that is a
    folder the person owns, else in the OS temporary folder, and a shell can write there.

  One case is the opposite of a gap: a command nested more than 32 levels deep (`$(` inside `$(`
  and so on) cannot be read, so the gate refuses it outright.
- **Only for sessions started at the brain root**, where `.claude/settings.json` is read.
- **Per session.** Runs are kept in that state folder against the session id; a new session has run
  nothing.
- **Open on its own failure.** If the gate itself errors, the write goes through with a visible
  warning instead of blocking every tool call.
