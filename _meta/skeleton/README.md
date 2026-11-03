# {{name}}

{{description}}

This folder is a brain: a git repository that keeps the knowledge, skills and scripts for one area of
work in one place, so an agent session started here picks them up and the work builds on itself. Its
own skills are named `{{prefix}}-<name>`. `CLAUDE.md` is the agent's entry point and `docs/README.md`
indexes what has been written down. `_meta/`, the `brain-*` skills and the managed block at the top of
`CLAUDE.md` come from the brain template and are refreshed with `_meta/brain update`; everything else
is this brain's own.

Start every session in this folder. Things to say:

- "What's in this brain, and is anything wrong with it?"
- "That's the second time we've done this. Make it a routine." (a skill)
- "Remember what we just found out." (a practice)
- "That went wrong. Work out why and how to stop it happening again." (a retro)
- "Save this." or "Back this brain up online."
- "Update this brain from the template."
