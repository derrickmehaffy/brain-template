# {{name}}

{{description}}

This folder is a brain: a git repository that keeps the knowledge, skills and scripts for one area of
work in one place, so an agent session started here picks them up and the work builds on itself. Its
own skills are named `{{prefix}}-<name>`. `CLAUDE.md` is the agent's entry point and `docs/README.md`
indexes what has been written down. `_meta/`, the `brain-*` skills and the managed block at the top of
`CLAUDE.md` come from the brain template and are refreshed with `_meta/brain update`; everything else
is this brain's own.
