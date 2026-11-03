// Live pieces: the motion Client where the mod handed the kit its Clients, still text elsewhere.
import type { KitEnv, Tone } from './types'
import { GLYPH, INK, TONE_TEXT } from './tokens'

// What is happening now, and for how long.
export function Live(env: KitEnv, p: { key: string; text: string; since: number | null; tone?: Tone }) {
  const { Text } = env.el
  if (env.clients) return env.clients.motion(p.key, { kind: 'live', text: p.text, since: p.since, tone: p.tone ?? 'claude' })
  return <Text key={p.key} color={INK.ink3} wrap="truncate-end"><Text color={TONE_TEXT[p.tone ?? 'claude']}>{`${GLYPH.working} `}</Text>{p.text}</Text>
}

// Time to a due moment: amber within `soonHours`, red once it has passed.
export function Countdown(env: KitEnv, p: { key: string; until: number; now: number; soonHours?: number }) {
  const { Text } = env.el
  const soon = p.soonHours ?? 8
  if (env.clients) return env.clients.motion(p.key, { kind: 'countdown', until: p.until, soonHours: soon })
  // Never name a variable `h` in a .tsx file: it is the JSX factory, and shadowing it breaks every tag below.
  const hours = Math.round((p.until - p.now) / 3_600_000)
  return <Text key={p.key} color={hours < 0 ? TONE_TEXT.alert : hours < soon ? TONE_TEXT.you : INK.ink2}>{hours < 0 ? `◷ ${-hours}h overdue` : `◷ ${hours}h left`}</Text>
}

// A few short facts in turn, for an idle band. Still, it shows the first.
export function Ticker(env: KitEnv, p: { key: string; items: string[]; every?: number }) {
  const { Text } = env.el
  if (env.clients) return env.clients.motion(p.key, { kind: 'ticker', items: p.items, every: p.every ?? 3000 })
  return <Text key={p.key} color={INK.ink3} wrap="truncate-end">{p.items[0] ?? ''}</Text>
}

// How far something got, as a line of text that fits in a row.
export function StepBar(env: KitEnv, p: { key: string; done: number; total: number; tone: Tone }) {
  const { Text } = env.el
  const total = Math.max(1, p.total)
  const done = Math.max(0, Math.min(total, p.done))
  return <Text key={p.key}><Text color={TONE_TEXT[p.tone]}>{'━'.repeat(done)}</Text><Text color={INK.ink3}>{'─'.repeat(total - done)}</Text><Text color={INK.ink3}>{` ${done} of ${total}`}</Text></Text>
}
