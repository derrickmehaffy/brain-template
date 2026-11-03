# Skills

Every brain starts with the same meta skills: the ones that write, check and save everything else. A brain's own
skills are named `<prefix>-<verb>-<object>` and written through `brain-write-skill`.

Eight meta skills ship in every brain:

| Skill | One line |
| --- | --- |
| `brain-write-skill` | Create, change, split or rename one of the brain's skills, starting from where it sits in the routing map; write a router when an entry point fans out; gate output that must not be improvised; write the report-only agents a skill dispatches. |
| `brain-write-script` | Decide whether code earns a file, place it by the system it touches, keep it read-only unless its name says otherwise, and record what the system can and cannot do; connect a system's MCP server in `.mcp.json`. |
| `brain-write-practice` | Record one verified fact with its evidence and how to re-check it, after ruling out a duplicate; add a term that misled to the glossary. |
| `brain-retro` | When a skill went wrong or work fit no skill: log it and propose the one change that fixes it; review which skills go unused (`_meta/brain usage`). |
| `brain-upstream` | Record a proposed change to a template-owned file for the template to take in. |
| `brain-sync` | Run the checks, commit with a scoped subject, pull with rebase, push when asked. |
| `brain-write-mod` | Make a mod (a pane, band, command or tool-call hook inside Claude Code) from the kit in `_meta/modkit/`: read-only by default, tested, kept in `.claude/mods/<prefix>-<name>/`. See [Building mods](../guides/building-mods.md). |
| `brain-setup` | Turn a copy of the template into a brain; in a brain, explain it, repair what `doctor` reports and run `update`. |

Two skills work on the template itself and are never copied into a brain:

| Skill | One line |
| --- | --- |
| `template-make-brain` | Create a brain with `new`, or adopt a folder with `adopt`, after the setup questions and a dry run. |
| `template-intake` | Take in the upstream suggestions brains have recorded, with the person, and answer each in the changelog. |
