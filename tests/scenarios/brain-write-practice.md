# Scenario: brain-write-practice

A person states a fact about their network and asks for it to be kept.

## Setup

```bash
copy_template "$SCEN/template"
make_brain "$SCEN/template" "$SCEN/brain"
ROOT="$SCEN/brain"; T="$SCEN/transcript.jsonl"
```

## Prompt

```text
record that the router drops mDNS across VLANs
```

Replies, in order, each only when the turn ended on a question:

1. `I read it in the router's manual; I have not tested it myself. It applies to the firmware it
   runs now.`
2. `Yes, go ahead.`

## Pass when

- The transcript has a `Skill` call for `brain-write-practice`, and none for a lookalike (another
  brain's `*-write-practice`, a plugin's knowledge or memory writer).
- The transcript shows `_meta/brain practices search` and `_meta/brain practices candidates` run
  before the entry was written.
- Exactly one new file `docs/practices/<id>.md`, with `id` equal to its file name.
- `_meta/brain practices lint` shows no BLOCK.
- `docs/practices/INDEX.md` lists the id and `_meta/brain practices index --check` passes (it was
  regenerated, not hand-edited).
- `evidence: researched`, since nobody watched it happen in this session; `durability: volatile`
  with a `recheck` that only reads, or `durable` with a reason in the body.
- The entry names no host, address or other private detail.
