# Scenario: brain-write-script

A person keeps rewriting the same one-off query and says so.

## Setup

```bash
copy_template "$SCEN/template"
make_brain "$SCEN/template" "$SCEN/brain"
ROOT="$SCEN/brain"; T="$SCEN/transcript.jsonl"

# Something to count: an ignored folder with one sparse 1.5 GB file and one small one.
mkdir -p "$ROOT/downloads"
python3 -c 'import sys; f = open(sys.argv[1], "wb"); f.seek(1500 * 1024 * 1024); f.write(b"\0"); f.close()' \
  "$ROOT/downloads/disk image.iso"
echo "notes" > "$ROOT/downloads/notes.txt"
```

## Prompt

```text
I keep rewriting this query: count files over 1 GB in this folder
```

Replies, in order, each only when the turn ended on a question:

1. `This folder and everything under it. 1 GB means 1024 x 1024 x 1024 bytes.`
2. `Yes, go ahead.`

## Pass when

- The transcript has a `Skill` call for `brain-write-script`, and none for a script-writing
  lookalike (another brain's `*-write-script`, a plugin's script or tool writer).
- A script under `scripts/<system>/` (for example `scripts/files/count_large_files.py`), its folder
  named as a Python identifier with an `__init__.py`; the file name does not start `apply_`,
  `write_` or `delete_`.
- Its docstring opens `WHY THIS EXISTS:`; it holds no absolute or home path, and finds the brain
  root by walking up to `brain.json`.
- Tests in `scripts/tests/test_<system>_*.py`, one of them asserting the script only reads, and
  `python3 -m unittest discover -s ./scripts/tests -t ./scripts` passes from the brain root.
- `docs/CAPABILITIES.md` has a row for the system dated the day of the run, with what it cannot do.
- `_meta/brain doctor --quick` shows no BLOCK.
