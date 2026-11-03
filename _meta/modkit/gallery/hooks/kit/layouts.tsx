// Layouts for a pane, and for the band above the prompt. A layout takes its zones in order, top
// to bottom; a zone given nothing draws nothing and takes no room, so no heading ever sits over
// an empty list.
import type { El, KitEnv } from './types'
import { GLYPH, INK, TONE_TEXT } from './tokens'

export type Zone = El | El[] | null | false | undefined

const has = (z: Zone) => z !== null && z !== undefined && z !== false && !(Array.isArray(z) && z.filter(Boolean).length === 0)

function stack(env: KitEnv, key: string, zones: [string, Zone][]) {
  const { Box } = env.el
  return (
    <Box key={key} flexDirection="column" gap={1}>
      {zones.filter(([, z]) => has(z)).map(([name, z]) => <Box key={`${key}-${name}`} flexDirection="column" gap={1}>{z}</Box>)}
    </Box>
  )
}

// A summary: what matters most first, the rest folded.
export function Overview(env: KitEnv, p: { key?: string; header?: Zone; headline?: Zone; focus?: Zone; body?: Zone; folded?: Zone }) {
  return stack(env, p.key ?? 'overview', [['header', p.header], ['headline', p.headline], ['focus', p.focus], ['body', p.body], ['folded', p.folded]])
}

// Many items of one kind, in a list or a table.
export function Queue(env: KitEnv, p: { key?: string; header?: Zone; table?: Zone; footer?: Zone }) {
  return stack(env, p.key ?? 'queue', [['header', p.header], ['table', p.table], ['footer', p.footer]])
}

// One item in full.
export function Detail(env: KitEnv, p: { key?: string; backBar?: Zone; identity?: Zone; facts?: Zone; progress?: Zone; next?: Zone; sections?: Zone }) {
  return stack(env, p.key ?? 'detail', [['back', p.backBar], ['identity', p.identity], ['facts', p.facts], ['progress', p.progress], ['next', p.next], ['sections', p.sections]])
}

// A question for the person, with what they need to answer it.
export function DecisionLayout(env: KitEnv, p: { key?: string; context?: Zone; question?: Zone; evidence?: Zone; choices?: Zone }) {
  return stack(env, p.key ?? 'decision', [['context', p.context], ['question', p.question], ['evidence', p.evidence], ['choices', p.choices]])
}

// Nothing yet, reading, failed: whichever applies.
export function States(env: KitEnv, p: { key?: string; empty?: Zone; loading?: Zone; failed?: Zone }) {
  return stack(env, p.key ?? 'states', [['empty', p.empty], ['loading', p.loading], ['failed', p.failed]])
}

// The band is one row. Nothing in it is taller than a control, and its right edge is left free
// for the band's own collapse control.
function bandRow(env: KitEnv, key: string, left: Zone, middle: Zone, right: Zone) {
  const { Box } = env.el
  return (
    <Box key={key} flexDirection="row" alignItems="center" gap={1} paddingRight={5}>
      {has(left) && <Box flexDirection="row" gap={1} flexShrink={0} alignItems="center">{left}</Box>}
      <Box flexDirection="row" gap={1} flexGrow={1} flexShrink={1} minWidth={0} alignItems="center" marginLeft={1}>{has(middle) ? middle : null}</Box>
      {has(right) && <Box flexDirection="row" gap={1} flexShrink={0} alignItems="center">{right}</Box>}
    </Box>
  )
}

// Nothing waits: shortcuts on the left, a ticker of facts in the middle.
export function BandIdle(env: KitEnv, p: { key?: string; shortcuts: El[]; ticker?: El }) {
  return bandRow(env, p.key ?? 'band-idle', p.shortcuts, p.ticker, null)
}

// Claude is working: shortcuts, what it is on, the live line.
export function BandWorking(env: KitEnv, p: { key?: string; shortcuts: El[]; live: El; label: string }) {
  const { Text } = env.el
  return bandRow(env, p.key ?? 'band-working', p.shortcuts, [<Text key="n" bold>{p.label}</Text>, p.live], null)
}

// Something waits on the person: the question and its one or two buttons.
export function BandDecision(env: KitEnv, p: { key?: string; question: string; note?: string; actions: El[] }) {
  const { Text } = env.el
  return bandRow(env, p.key ?? 'band-decision', <Text key="g" bold color={TONE_TEXT.you}>{GLYPH.needs}</Text>,
    [<Text key="q" bold wrap="truncate-end">{p.question}</Text>, p.note ? <Text key="n" color={INK.ink3} wrap="truncate-end">{p.note}</Text> : null],
    p.actions)
}
