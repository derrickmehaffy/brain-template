# modkit-starter

Shows what this brain's health check says needs attention, without changing anything.

| | |
| --- | --- |
| Shows | a band above the prompt while something needs attention; a pane (`/modkit-starter`); a word in the status line |
| Reads | `_meta/brain doctor --quick`, at session start, on `/modkit-starter refresh`, and after a turn at most every five minutes |
| Writes | nothing. Its buttons only put a request in the prompt for you to send |
| Surfaces | terminal and desktop draw it all; VS Code draws the pane, not the band; `claude -p` and a phone get the command's text reply |
| Turn it off | `"modkit-starter@skills-dir": false` under `enabledPlugins` in `.claude/settings.local.json`, or delete `.claude/skills/modkit-starter` |

## Files

| File | What |
| --- | --- |
| `hooks/register.tsx` | the hooks: the command, the pane, the band, the button acts and their validator |
| `hooks/health.ts` | where the data comes from, and how it is read; replace this to show something else |
| `hooks/kit/` | a copy of the brain's mod kit. Never edit it here: `_meta/brain mods sync` refreshes it |
| `types/index.d.ts` | the values the mod keeps in `$.state` |
| `tests/` | `claude plugin test` runs these with no session, sign-in or network |

## Checks

```bash
_meta/brain mods check modkit-starter    # claude plugin validate, then claude plugin test
```
