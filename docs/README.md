# Docs

Everything about making a brain, growing it and understanding what it does underneath. Pick the line
that sounds like you.

| You are… | Start with |
| --- | --- |
| New to all of this, and have never used git or a terminal | [Start here](guides/start-here.md): every click, with Claude doing the technical parts |
| Deciding how a brain should fit your work | [Choosing a shape](guides/choosing-a-shape.md): one project, several, massive, or a hub |
| Setting one up and wondering what to say | [Prompts](guides/prompts.md): things to say at each step |
| Living with a brain, and wanting it to get better | [Making a brain, and letting it grow](guides/making-a-brain.md) |
| Technical, and want to know exactly what happens | [Reference](reference/): commands, what loads where, the gate, the guard |
| Building a mod for your brain (a pane, a status band, a hook) | [Building mods](guides/building-mods.md) |

## Guides

For everyone. Plain words, pictures, and what to say to Claude.

- [Start here](guides/start-here.md): from nothing to a working brain.
- [Choosing a shape](guides/choosing-a-shape.md), then the shape that fits:
  - [Single project](guides/single-project.md): one project you keep coming back to;
  - [Multi-project](guides/multi-project.md): several repos that belong together;
  - [Massive brain](guides/massive-brain.md): many repos and several kinds of work;
  - [Brain of brains](guides/brain-of-brains.md): one place to ask, handing work to your other brains.
- [Making a brain, and letting it grow](guides/making-a-brain.md): when to make one, and how it learns.
- [Prompts](guides/prompts.md): things to say, by step and by kind of work.
- [Building mods](guides/building-mods.md): extending Claude's own interface for your brain.

## Reference

For the technical reader: [the index](reference/README.md), or straight to
[commands](reference/commands.md), [what loads where](reference/what-loads-where.md),
[setting up](reference/setting-up.md), [skills](reference/skills.md),
[routing and the gate](reference/routing-and-the-gate.md),
[secrets and systems](reference/secrets-and-systems.md), [the privacy guard](reference/privacy-guard.md),
[updates and upstream](reference/updates-and-upstream.md) and [several brains](reference/several-brains.md).

## The rest of this folder

- `images/`: the pictures in the README and the guides. They are hand-written SVGs, each on its own
  background. Edit the light ones, then run `python3 docs/images/make-dark.py` to write the
  `-dark.svg` partners that GitHub shows in its dark theme.
- `superpowers/`: the template's original design (`specs/`) and build plan (`plans/`).

All of `docs/` belongs to the template. A brain gets its own `docs/` from the skeleton; at setup, the
person can keep `guides/`, `images/` and `reference/` until they ask for them to go.
