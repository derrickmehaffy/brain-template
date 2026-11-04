# The mod kit

A brain's **mods** change Claude Code itself: a pane beside the chat, a band above the prompt, a
slash command, a word in the status line, a hook on tool calls. This folder is what every brain's
mods start from. It ships with the template and `update` replaces it, so a brain never edits it.
The guide for people is `docs/guides/building-mods.md` in the template; the skill is `brain-write-mod`.

| Folder | What |
| --- | --- |
| `gallery/hooks/kit/` | **the kit**: tokens, pieces and layouts a mod draws with, on every surface |
| `gallery/` | a mod of its own, `/modkit`, that draws every piece with made-up data, and the kit's tests |
| `starter/` | the mod `_meta/brain mods new <name>` copies: a band, a pane and a command that show what the brain's health check says needs attention |

## How a brain's mods are laid out

```text
.claude/mods/<prefix>-<name>/  the mod, committed with the rest of .claude/
  .claude-plugin/plugin.json   name, description, "types"; "defaultEnabled": false for an opt-in mod
  hooks/hooks.json             { "modules": ["./register.tsx"] }
  hooks/register.tsx           the hooks module
  hooks/kit/                   a copy of the kit (a mod imports only from its own folder)
  types/index.d.ts             the values it keeps in $.state
  tests/*.test.ts              claude plugin test
  README.md                    what it shows, reads and writes, and how to turn it off
.claude/skills/<prefix>-<name> -> ../mods/<prefix>-<name>   the link that loads it
```

Claude Code loads a plugin folder it finds in the project's `.claude/skills/`, in a session started
at the brain's root once the folder is trusted, and reloads it when one of its files is saved. Mods
live under `.claude/`, Claude's own space, so a `mods/` folder the person already has (whatever it
holds) is never mistaken for one, nor saved because of one. The link is committed, so every clone of the brain gets the same mods. `_meta/brain mods` does the rest:

| Command | Does |
| --- | --- |
| `mods list` | each mod: linked or not, kit current or stale, opt-in or not |
| `mods new <name>` | `.claude/mods/<prefix>-<name>/` from the starter, with the kit and the link (`--dry-run` first) |
| `mods sync` | copies the kit into every mod that has `hooks/kit/` (`--check` changes nothing) |
| `mods link [name]` | makes a missing link |
| `mods check [name]` | `claude plugin validate` and `claude plugin test` on each mod |
| `mods ready` | which Claude Code on this machine runs mods |

`lint` reports a mod with no manifest, a name that is not the folder's, a missing link, a stale kit
copy, no tests or no README.

## Using the kit in a mod

Build the kit once per drawing, in each `ui.render` hook, and hand presses back through one
validator. The Client module paths must be string literals in the entry file: the engine reads them
off its source when the mod loads. `starter/hooks/register.tsx` is a working example of all of it.

```tsx
const els = $.ui.resolve(e)
const k = makeKit({
  el: els, surface: e.surface, width: e.props.bodyColumns || 60,
  clients: 'Client' in els && e.surface === 'desktop' ? {
    button: (key, p) => <els.Client key={key} module="./kit/button.tsx" props={p} />,
    motion: (key, p) => <els.Client key={key} module="./kit/motion.tsx" props={p} />,
  } : undefined,
  perform: act => { const a = actOf(act); if (a) void run($, a) },
})
return k.Overview({ header: k.Section({ key: 'h', title: 'Today' }), body: k.List({ key: 'l', children: rows }) })
// and once, for desktop presses:
on('ui.message', async ($, e, next) => (onMessage(e, actOf, a => void run($, a)) ? {} : next(e)))
```

`actOf` is the mod's own validator: a button carries plain data (`{ do: 'refresh' }`), and only an
act the validator accepts runs. A button never carries free text, a path or a command.

## Rules the pieces keep

- **One primary button per view**, named for what it does.
- **Colour never alone.** Each tone comes with a glyph or a word: ✓ done, ▸ now, · to come,
  ● working, ! needs you, ✗ failed.
- **Theme names for text and lines** (`text`, `inactive`, `subtle`, `warning`, `success`, `error`,
  `suggestion`, `autoAccept`), so light and dark follow the app. Hex only for tints and charts.
- **Actions share one width and times one column** in a list (`COLUMN` in `tokens.ts`).
- **The band is one row**, nothing taller than a control, its right edge left for its collapse control.
- **A zone with nothing to show takes no room**: no heading over an empty list.
- **A button that asks Claude for something fills the prompt** (`$.prompt.fill`); the person sends it.
- **Every surface draws something**: Clients, Svg, Input and Select are looked up and fall back to text.

| Tone | Means | Text colour | Tint |
| --- | --- | --- | --- |
| `claude` | Claude is doing it | `autoAccept` | `#7161e0` at 13% |
| `you` | waits on the person | `warning` | `#a66a00` at 13% |
| `ok` | done, healthy | `success` | `#009300` at 13% |
| `alert` | failed, blocked, overdue | `error` | `#d03b3b` at 13% |
| `info` | next, selected | `suggestion` | `#2a78d6` at 13% |
| `neutral` | anything else | `inactive` | none |

| File | Pieces |
| --- | --- |
| `controls.tsx` | Button, IconButton, Tabs, Chips, PromptChip, Confirm, Fold, Field, Picker |
| `content.tsx` | Section, Card, Pill, Notice, KeyValue, Banner, Next, Decision, Empty, Loading, Failed, Timeline, Checklist, Link, Prose |
| `lists.tsx` | Row, List, Table |
| `dashboard.tsx` | StatTile, Stats, Metrics, Meter, Distribution, Sparkline |
| `live.tsx` | Live, Countdown, Ticker, StepBar |
| `chartpieces.tsx` | StepRail, Ring (SVG text in `charts.ts`) |
| `layouts.tsx` | Overview, Queue, Detail, DecisionLayout, States, BandIdle, BandWorking, BandDecision |

## What the surfaces do (found while building the kit; recheck after a Claude Code update)

| Fact | So the kit |
| --- | --- |
| On the desktop, the first click into an unfocused pane could reach a host Button with a stale handle and be dropped (October 2026) | draws desktop buttons as a Client (`button.tsx`) that posts its act |
| Inside a Client: Box, Text and a label-only Button; no Markdown, Link or hover | keeps rich content in the hooks-drawn tree |
| A Client's props holding `undefined` anywhere refuses the whole tree | leaves a missing badge out rather than passing `undefined` |
| A width in % must be a whole number; a fraction refuses the whole drawing | sends every % through `pct()` |
| An `isInteractive` Svg is a lazily loaded frame that flashes as a pane scrolls | never passes it; a test checks |
| JSX compiles to calls of the global `h` | never names a variable `h` in a `.tsx` file |
| Mobile's element table hands back stand-ins for Input and Select that draw nothing | decides by `e.surface`, not by whether the element exists |
| VS Code has no Client; the terminal has no Svg | falls back to host Buttons and to words |

## Developing the kit

Edit `gallery/hooks/kit/`, then look at it: `claude --plugin-dir _meta/modkit/gallery`, run
`/modkit`, once in the dark theme and once in the light. Tests (they need the `claude` CLI, and run
with no session, sign-in or network):

```bash
claude plugin test _meta/modkit/gallery
```

The starter is tested with a kit copied in, which `tests/test_modkit.py` in the template does in a
temporary folder whenever `claude` is on PATH.
