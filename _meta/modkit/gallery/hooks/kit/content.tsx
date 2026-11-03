// Content pieces. Desktop and terminal share the code; where a terminal would spend rows on a
// border, it gets a word in brackets instead.
import type { ButtonSpec, El, KitEnv, Tone } from './types'
import { COLUMN, GLYPH, INK, NEUTRAL, TONE_TEXT, edge, tint, pct } from './tokens'
import { Button } from './controls'

const isDesk = (env: KitEnv) => env.surface === 'desktop'

// A heading over a group: bold title, a dim rule to the right edge, then a note or an action.
export function Section(env: KitEnv, p: { key: string; title: string; note?: string; action?: El }) {
  const { Box, Text } = env.el
  const used = p.title.length + (p.note ? p.note.length + 2 : 0) + (p.action ? 12 : 0) + 4
  const fill = Math.max(2, Math.min(200, env.width - used))
  return (
    <Box key={p.key} flexDirection="row" alignItems="center" gap={1}>
      <Box flexShrink={0}><Text bold wrap="truncate-end">{p.title}</Text></Box>
      <Box flexGrow={1} flexShrink={1} minWidth={2} overflow="hidden"><Text color={INK.line} wrap="truncate">{'─'.repeat(fill)}</Text></Box>
      {p.note && <Box flexShrink={0}><Text color={INK.ink3} wrap="truncate-end">{p.note}</Text></Box>}
      {p.action && <Box flexShrink={0}>{p.action}</Box>}
    </Box>
  )
}

// A card: tinted by tone for what needs attention, neutral otherwise. The desktop pads a
// bordered Box itself, so no padding is given here.
export function Card(env: KitEnv, p: { key: string; tone: Tone; title: string; count?: string; children: El }) {
  const { Box, Text } = env.el
  return (
    <Box key={p.key} flexDirection="column" gap={1} borderStyle="round" borderColor={edge(p.tone)} backgroundColor={tint(p.tone)}>
      <Box flexDirection="row" justifyContent="space-between" gap={2}>
        <Box flexShrink={1} minWidth={0}><Text wrap="truncate-end"><Text color={TONE_TEXT[p.tone]}>{`${GLYPH.working} `}</Text><Text bold>{p.title}</Text></Text></Box>
        {p.count && <Box flexShrink={0}><Text color={INK.ink3}>{p.count}</Text></Box>}
      </Box>
      {p.children}
    </Box>
  )
}

// A short status word: a tinted chip on the desktop, [word] elsewhere.
export function Pill(env: KitEnv, p: { key: string; tone: Tone; text: string }) {
  const { Box, Text } = env.el
  if (!isDesk(env)) return <Text key={p.key} color={TONE_TEXT[p.tone]}>{`[${p.text}]`}</Text>
  return (
    <Box key={p.key} flexShrink={0} borderStyle="single" borderColor={edge(p.tone)} backgroundColor={tint(p.tone)} paddingX={0.5} paddingY={0}>
      <Text color={TONE_TEXT[p.tone]}>{p.text}</Text>
    </Box>
  )
}

// One line saying what just happened, tinted by how it went.
export function Notice(env: KitEnv, p: { key: string; tone: 'ok' | 'you' | 'alert'; text: string }) {
  const { Box, Text } = env.el
  const glyph = p.tone === 'ok' ? GLYPH.done : p.tone === 'alert' ? GLYPH.failed : GLYPH.needs
  return (
    <Box key={p.key} borderStyle="round" borderColor={edge(p.tone)} backgroundColor={tint(p.tone)} paddingX={1}>
      <Text color={TONE_TEXT[p.tone]} wrap="wrap">{`${glyph} ${p.text}`}</Text>
    </Box>
  )
}

// Facts as label and value, the labels in one column.
export function KeyValue(env: KitEnv, p: { key: string; pairs: [string, El | string][] }) {
  const { Box, Text } = env.el
  return (
    <Box key={p.key} flexDirection="column">
      {p.pairs.map(([k, v]) => (
        <Box key={k} flexDirection="row" gap={1}>
          <Box width={COLUMN.key} flexShrink={0}><Text color={INK.ink3}>{k}</Text></Box>
          {typeof v === 'string' ? <Text wrap="wrap">{v}</Text> : v}
        </Box>
      ))}
    </Box>
  )
}

// Something that affects everything on screen: a tinted line with at most one action.
export function Banner(env: KitEnv, p: { key: string; tone: 'alert' | 'you' | 'info'; text: string; action?: ButtonSpec }) {
  const { Box, Text } = env.el
  return (
    <Box key={p.key} flexDirection="row" alignItems="center" gap={1} borderStyle="round" borderColor={edge(p.tone)} backgroundColor={tint(p.tone)} paddingX={1}>
      <Text color={TONE_TEXT[p.tone]}>{p.tone === 'alert' ? GLYPH.failed : GLYPH.needs}</Text>
      <Box flexGrow={1} minWidth={0}><Text wrap="wrap">{p.text}</Text></Box>
      {p.action && Button(env, p.action)}
    </Box>
  )
}

// The one thing to do next. The view's accent goes here, and nowhere else.
export function Next(env: KitEnv, p: { key: string; text: string; reason?: string; actions?: El[] }) {
  const { Box, Text } = env.el
  return (
    <Box key={p.key} flexDirection="column">
      {Section(env, { key: `${p.key}-h`, title: 'Next' })}
      <Text bold color={TONE_TEXT.info} wrap="wrap">{p.text}</Text>
      {p.reason && <Text color={INK.ink3} wrap="wrap">{p.reason}</Text>}
      {p.actions && p.actions.length > 0 && <Box flexDirection="row" gap={1} marginTop={1}>{p.actions}</Box>}
    </Box>
  )
}

// A choice for the person: what it is about, the question, the evidence, the choices.
export function Decision(env: KitEnv, p: { key: string; context: string; question: string; evidence: string; choices: El[]; tone?: 'you' | 'alert' }) {
  const { Box, Text } = env.el
  const tone = p.tone ?? 'you'
  return (
    <Box key={p.key} flexDirection="column" gap={1} borderStyle="round" borderColor={edge(tone)} backgroundColor={tint(tone)}>
      <Text color={INK.ink3}>{p.context}</Text>
      <Text bold wrap="wrap"><Text color={TONE_TEXT[tone]}>{`${GLYPH.needs} `}</Text>{p.question}</Text>
      <Box flexDirection="row" gap={1}>
        <Text color={INK.lineStrong}>│</Text>
        <Box flexShrink={1}><Text color={INK.ink2} wrap="wrap">{p.evidence}</Text></Box>
      </Box>
      <Box flexDirection="row" gap={1} flexWrap="wrap">{p.choices}</Box>
    </Box>
  )
}

// The three states every view needs: nothing yet, reading, and it failed.
export function Empty(env: KitEnv, p: { key: string; title: string; text: string; command?: string }) {
  const { Box, Text } = env.el
  return (
    <Box key={p.key} flexDirection="column">
      <Text bold>{p.title}</Text>
      <Text wrap="wrap"><Text color={INK.ink2}>{p.text}</Text>{p.command && <Text bold color={TONE_TEXT.info}>{` ${p.command}`}</Text>}</Text>
    </Box>
  )
}

export function Loading(env: KitEnv, p: { key: string; label: string; lines: number[] }) {
  const { Box, Text } = env.el
  return (
    <Box key={p.key} flexDirection="column" gap={0.5}>
      <Text color={INK.ink3}>{p.label}</Text>
      {p.lines.map((share, i) => isDesk(env)
        // A Box's height counts whole lines on the desktop: half a line draws a bar.
        ? <Box key={`${p.key}-${i}`} width={pct(share)} height={0.5} backgroundColor={NEUTRAL.track} />
        : <Text key={`${p.key}-${i}`} color={INK.ink3}>{'░'.repeat(Math.max(4, Math.round(share / 3)))}</Text>)}
    </Box>
  )
}

export function Failed(env: KitEnv, p: { key: string; text: string; retry?: ButtonSpec }) {
  return Banner(env, { key: p.key, tone: 'alert', text: p.text, action: p.retry })
}

// A history: when, a mark coloured by who acted, what happened.
export function Timeline(env: KitEnv, p: { key: string; events: { at: string; text: string; who: 'you' | 'claude' | 'none' }[] }) {
  const { Box, Text } = env.el
  const mark = { you: TONE_TEXT.you, claude: TONE_TEXT.claude, none: INK.ink3 }
  return (
    <Box key={p.key} flexDirection="column">
      {p.events.map((ev, i) => (
        <Box key={`${p.key}-${i}`} flexDirection="row" gap={1}>
          <Box width={10} flexShrink={0} justifyContent="flex-end"><Text color={INK.ink3}>{ev.at}</Text></Box>
          <Text color={mark[ev.who]}>{ev.who === 'none' ? GLYPH.idle : GLYPH.working}</Text>
          <Text wrap="wrap" color={ev.who === 'none' ? INK.ink3 : undefined}>{ev.text}</Text>
        </Box>
      ))}
    </Box>
  )
}

// Checks: done, running, not needed (say why in the note), still to do.
export function Checklist(env: KitEnv, p: { key: string; items: { label: string; note?: string; state: 'done' | 'running' | 'na' | 'todo'; by?: string }[] }) {
  const { Box, Text } = env.el
  const mark = { done: [GLYPH.done, TONE_TEXT.ok], running: ['◌', TONE_TEXT.claude], na: [GLYPH.na, INK.ink3], todo: ['☐', INK.ink3] } as const
  return (
    <Box key={p.key} flexDirection="column">
      {p.items.map((it, i) => (
        <Box key={`${p.key}-${i}`} flexDirection="row" gap={1} justifyContent="space-between">
          <Box flexDirection="row" gap={1} flexShrink={1} minWidth={0}>
            <Text color={mark[it.state][1]}>{mark[it.state][0]}</Text>
            <Text wrap="truncate-end" color={it.state === 'na' || it.state === 'todo' ? INK.ink3 : undefined}>
              {it.label}{it.note ? <Text color={it.state === 'running' ? TONE_TEXT.claude : INK.ink3}>{` · ${it.note}`}</Text> : null}
            </Text>
          </Box>
          {it.by && <Text color={INK.ink3}>{it.by}</Text>}
        </Box>
      ))}
    </Box>
  )
}

// A link. The surface opens it itself, with no round trip through the mod. Only an https or
// http address becomes a link; anything else is drawn as its label, as plain text.
const WEB = /^https?:\/\/[^\s@]+$/

export function Link(env: KitEnv, p: { key: string; href: string; label: string }) {
  const { Link: L, Text } = env.el
  if (!L || !WEB.test(p.href)) return <Text key={p.key}>{p.label}</Text>
  return <L key={p.key} href={p.href} label={p.label} />
}

// A sentence or two with inline links, written as Markdown. No onLinkPress: the surface opens a
// link itself, which is both simpler and never lost to a redraw.
export function Prose(env: KitEnv, p: { key: string; text: string; dim?: boolean }) {
  const { Markdown, Text } = env.el
  if (!Markdown) return <Text key={p.key} wrap="wrap" dimColor={p.dim}>{p.text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1 ($2)')}</Text>
  return <Markdown key={p.key} text={p.text} dimColor={p.dim} />
}
