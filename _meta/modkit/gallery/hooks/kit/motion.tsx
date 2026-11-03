// The kit's moving parts on the desktop, in one Client module: a live line (a spinner, a light
// that sweeps the words, the time since it started), a countdown, and a ticker. Each runs on the
// Client's own clock, so it moves without the mod redrawing. The clock starts once, while the
// instance's state is still undefined.
import type { ClientSurface } from 'claude-code'

import { HUE, INK, TONE_TEXT } from './tokens'
import type { MotionProps, Tone } from './types'

type State = { frame: number }

const SPIN = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
const TICK_MS: Record<MotionProps['kind'], number> = { live: 90, countdown: 1000, ticker: 250 }

const hue = (t: Tone) => (t === 'neutral' ? TONE_TEXT.neutral : HUE[t])

function since(at: number | null): string {
  if (!at) return ''
  const s = Math.max(0, Math.floor((Date.now() - at) / 1000))
  return s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

function left(until: number, soonHours: number): { text: string; tone: Tone } {
  const s = Math.floor((until - Date.now()) / 1000)
  if (s < 0) {
    const days = Math.floor(-s / 86400)
    return { text: days >= 1 ? `◷ ${days}d overdue` : `◷ ${Math.floor(-s / 3600)}h overdue`, tone: 'alert' }
  }
  const days = Math.floor(s / 86400)
  const hours = Math.floor((s % 86400) / 3600)
  const mins = Math.floor((s % 3600) / 60)
  if (days >= 1) return { text: `◷ ${days}d ${hours}h`, tone: 'neutral' }
  const text = `◷ ${hours}h ${String(mins).padStart(2, '0')}m ${String(s % 60).padStart(2, '0')}s`
  return { text, tone: s < soonHours * 3600 ? 'you' : 'neutral' }
}

export default function Motion(p: MotionProps, surface: ClientSurface<State>) {
  const { Box, Text } = surface.elements
  if (surface.state === undefined) {
    surface.every(TICK_MS[p.kind], () => surface.setState({ frame: (surface.state?.frame ?? 0) + 1 }))
    surface.setState({ frame: 0 })
  }
  const frame = surface.state?.frame ?? 0
  if (p.kind === 'live') {
    const pass = p.text.length + 24
    const at = (frame % pass) - 7
    const a = Math.max(0, at)
    const b = Math.max(0, Math.min(p.text.length, at + 7))
    return (
      <Box flexDirection="row" justifyContent="space-between" gap={2}>
        <Box flexDirection="row" gap={1} flexShrink={1} minWidth={0}>
          <Text color={hue(p.tone)}>{SPIN[frame % SPIN.length]}</Text>
          <Text wrap="truncate-end"><Text dimColor>{p.text.slice(0, a)}</Text><Text color={hue(p.tone)}>{p.text.slice(a, b)}</Text><Text dimColor>{p.text.slice(b)}</Text></Text>
        </Box>
        <Box flexShrink={0}><Text dimColor>{since(p.since)}</Text></Box>
      </Box>
    )
  }
  if (p.kind === 'countdown') {
    const l = left(p.until, p.soonHours)
    return <Text color={l.tone === 'neutral' ? INK.ink2 : TONE_TEXT[l.tone]}>{l.text}</Text>
  }
  // The ticker counts frames: the Client's clock drives it on the desktop, and a test's advance().
  const i = Math.floor((frame * TICK_MS.ticker) / Math.max(1000, p.every)) % Math.max(1, p.items.length)
  return <Text dimColor wrap="truncate-end">{p.items[i] ?? ''}</Text>
}
