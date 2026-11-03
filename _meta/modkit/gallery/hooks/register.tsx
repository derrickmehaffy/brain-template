import { atom, read, update } from 'claude-code'
import type { EngineInterface, JsonValue, Register } from 'claude-code'

import { makeKit, onMessage } from './kit'
import type { Elements, Kit, MotionProps, PressProps } from './kit'
import { Pieces } from './gallery/pieces'
import { Numbers } from './gallery/numbers'
import { Layouts } from './gallery/layouts'
import { BandTab, BandView } from './gallery/band'
import type { BandShown, GalleryTab } from '../types'

// brain-modkit: the mod kit's gallery. /modkit opens a pane that draws every piece and layout
// with made-up data, on whichever surface the session has, so a change to the kit can be looked
// at in the terminal and on the desktop, light and dark. The library itself is hooks/kit/, which
// a brain's mods copy. The gallery reads and writes nothing outside its own state.

const PANE = 'brain-modkit'
const tab = atom({ plugin: 'brain-modkit', key: 'tab' } as const, 'pieces')
const notice = atom({ plugin: 'brain-modkit', key: 'notice' } as const, null)
const confirming = atom({ plugin: 'brain-modkit', key: 'confirming' } as const, null)
const chip = atom({ plugin: 'brain-modkit', key: 'chip' } as const, 'all')
const band = atom({ plugin: 'brain-modkit', key: 'band' } as const, null)

// Every act a gallery button may carry. A press is validated against this before it runs.
type Act =
  | { do: 'note'; text: string }
  | { do: 'tab'; tab: GalleryTab }
  | { do: 'confirm'; id: string | null }
  | { do: 'chip'; id: string }
  | { do: 'band'; state: BandShown | null }

const TABS: GalleryTab[] = ['pieces', 'numbers', 'layouts', 'band']
const BANDS: BandShown[] = ['idle', 'working', 'decision']

function actOf(a: unknown): Act | null {
  if (!a || typeof a !== 'object') return null
  const d = a as Record<string, unknown>
  const short = (v: unknown) => typeof v === 'string' && v.length > 0 && v.length <= 80
  switch (d['do']) {
    case 'note': return short(d['text']) ? { do: 'note', text: d['text'] as string } : null
    case 'tab': return TABS.includes(d['tab'] as GalleryTab) ? { do: 'tab', tab: d['tab'] as GalleryTab } : null
    case 'confirm': return d['id'] === null || short(d['id']) ? { do: 'confirm', id: d['id'] as string | null } : null
    case 'chip': return short(d['id']) ? { do: 'chip', id: d['id'] as string } : null
    case 'band': return d['state'] === null || BANDS.includes(d['state'] as BandShown) ? { do: 'band', state: d['state'] as BandShown | null } : null
    default: return null
  }
}

async function perform($: EngineInterface, a: Act): Promise<void> {
  if (a.do === 'note') await update($, notice, () => `Pressed: ${a.text}`)
  else if (a.do === 'tab') await update($, tab, () => a.tab)
  else if (a.do === 'confirm') await update($, confirming, () => a.id)
  else if (a.do === 'chip') await update($, chip, () => a.id)
  else await update($, band, () => a.state)
}

// The kit for one drawing. The Client module paths must be string literals in this entry file:
// the engine reads them off its source when the mod loads.
function kitFor($: EngineInterface, surface: string, width: number, els: Elements): Kit {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const Client = (els as any).Client
  return makeKit({
    el: els,
    surface,
    width,
    clients: Client && surface === 'desktop'
      ? {
        button: (key: string, p: PressProps) => <Client key={key} module="./kit/button.tsx" props={p} />,
        motion: (key: string, p: MotionProps) => <Client key={key} module="./kit/motion.tsx" props={p} />,
      }
      : undefined,
    perform: (act: JsonValue) => {
      const a = actOf(act)
      if (a) void perform($, a)
    },
  })
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'modkit', description: 'Show every piece and layout of the brain mod kit' })
    return next(e)
  })

  on('command.run', { command: 'modkit' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Mod kit' })
    return { text: 'Mod kit gallery open.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const els = $.ui.resolve(e)
    const k = kitFor($, e.surface, e.props.bodyColumns || 60, els)
    const { Box } = els
    const shown: GalleryTab = await read($, tab)
    const said = await read($, notice)
    const now = await $.clock.now()
    const state = { confirming: await read($, confirming), chip: await read($, chip) }
    return (
      <Box flexDirection="column" gap={1}>
        {k.Tabs({ key: 'gallery-tabs', on: `tab-${shown}`, items: [
          { id: 'tab-pieces', label: 'Pieces', act: { do: 'tab', tab: 'pieces' } },
          { id: 'tab-numbers', label: 'Numbers', act: { do: 'tab', tab: 'numbers' } },
          { id: 'tab-layouts', label: 'Layouts', act: { do: 'tab', tab: 'layouts' } },
          { id: 'tab-band', label: 'Band', act: { do: 'tab', tab: 'band' } },
        ] })}
        {said && k.Notice({ key: 'gallery-notice', tone: 'ok', text: said })}
        {shown === 'pieces' ? Pieces(k, state)
          : shown === 'numbers' ? Numbers(k, now)
            : shown === 'layouts' ? Layouts(k)
              : BandTab(k)}
      </Box>
    )
  })

  on('ui.message', async ($, e, next) => {
    const handled = onMessage(e, actOf, a => void perform($, a))
    return handled ? {} : next(e)
  })

  // The band: drawn only while one is chosen on the Band tab, so the rest of the time the band
  // above the prompt is the engine's own (or another mod's).
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const shown = await read($, band)
    if (!shown || e.props.hasSurvey) return next(e)
    const k = kitFor($, e.surface, e.props.bodyColumns || 80, $.ui.resolve(e))
    return BandView(k, shown, await $.clock.now())
  })
}
