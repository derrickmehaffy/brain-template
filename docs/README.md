# Docs

The template's own documents. They are template-only: a brain made from the template never gets
them, its `docs/` comes from the skeleton.

- `guides/`: for people making a brain: `start-here.md` (from nothing to a brain, for someone who
  has never used git or a terminal), `making-a-brain.md` (what a brain is for, setup, how it
  grows) and `prompts.md` (what to say at each step, and starting points for common kinds of work).
- `images/`: the README's banner and diagrams, also used by the guides: hand-written SVGs, each on its
  own background. Edit the light ones, then run `python3 docs/images/make-dark.py` to write the
  `-dark.svg` partners that GitHub shows in its dark theme.
- `superpowers/`: the design (`specs/`) and the build plan (`plans/`).
