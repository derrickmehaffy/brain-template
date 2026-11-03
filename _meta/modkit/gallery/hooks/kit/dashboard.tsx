// Numbers at a glance. Bars are Boxes sized in whole percentages, so they need no Svg; outside
// the desktop they draw as text bars.
import type { El, KitEnv, Tone } from './types'
import { HUE, INK, NEUTRAL, TONE_TEXT, edge, tint, pct } from './tokens'

const barHue = (t: Tone | 'other') => (t === 'neutral' || t === 'other' ? NEUTRAL.bar : HUE[t])

// One number, its label, and how it moved. Several sit side by side in Stats.
export function StatTile(env: KitEnv, p: { key: string; value: string; label: string; delta?: { text: string; tone: Tone }; tone?: Tone }) {
  const { Box, Text } = env.el
  const tone = p.tone ?? 'neutral'
  return (
    <Box key={p.key} flexDirection="column" flexGrow={1} minWidth={0} borderStyle="round" borderColor={edge(tone)} backgroundColor={tint(tone)}>
      <Text bold color={tone === 'neutral' ? undefined : TONE_TEXT[tone]}>{p.value}</Text>
      <Text color={INK.ink3} wrap="truncate-end">{p.label}</Text>
      {p.delta && <Text color={TONE_TEXT[p.delta.tone]} wrap="truncate-end">{p.delta.text}</Text>}
    </Box>
  )
}

export function Stats(env: KitEnv, p: { key: string; tiles: El[] }) {
  const { Box } = env.el
  return <Box key={p.key} flexDirection="row" gap={1}>{p.tiles}</Box>
}

// The numbers in one line, lighter than tiles: a bold value in its tone, then a dim label.
export function Metrics(env: KitEnv, p: { key: string; items: { value: string; label: string; tone?: Tone }[] }) {
  const { Box, Text } = env.el
  return (
    <Box key={p.key} flexDirection="row" flexWrap="wrap" columnGap={3} rowGap={0}>
      {p.items.map((it, i) => (
        <Box key={`${p.key}-${i}`} flexDirection="row" gap={1} flexShrink={0}>
          <Text bold color={it.tone && it.tone !== 'neutral' ? TONE_TEXT[it.tone] : INK.ink}>{it.value}</Text>
          <Text color={INK.ink3}>{it.label}</Text>
        </Box>
      ))}
    </Box>
  )
}

// Use against a limit: parts stack left to right, and `cap` draws a mark where the limit is.
export function Meter(env: KitEnv, p: { key: string; label: string; parts: { value: number; tone: Tone }[]; max: number; cap?: number; note: string }) {
  const { Box, Text } = env.el
  const max = Math.max(1, p.max)
  if (env.surface !== 'desktop') {
    const cells = 20
    const filled = p.parts.map(x => ({ n: Math.round((x.value / max) * cells), tone: x.tone }))
    const used = filled.reduce((a, b) => a + b.n, 0)
    return (
      <Box key={p.key} flexDirection="row" gap={1}>
        <Box width={10} flexShrink={0}><Text color={INK.ink2}>{p.label}</Text></Box>
        <Text>{filled.map((f, i) => <Text key={i} color={TONE_TEXT[f.tone]}>{'█'.repeat(f.n)}</Text>)}<Text color={INK.ink3}>{'░'.repeat(Math.max(0, cells - used))}</Text></Text>
        <Text color={INK.ink3}>{p.note}</Text>
      </Box>
    )
  }
  const track = Math.max(10, env.width - 30)
  const capAt = p.cap === undefined ? null : Math.round((p.cap / max) * track)
  return (
    <Box key={p.key} flexDirection="row" alignItems="center" gap={1}>
      <Box width={10} flexShrink={0}><Text color={INK.ink2}>{p.label}</Text></Box>
      <Box width={track} height={0.5} flexDirection="row" backgroundColor={NEUTRAL.track} position="relative">
        {p.parts.map((x, i) => <Box key={i} width={pct((x.value / max) * 100)} height={0.5} backgroundColor={barHue(x.tone)} />)}
        {capAt !== null && <Box position="absolute" top={0} left={capAt} width={0.2} height={0.5} backgroundColor={NEUTRAL.mark} />}
      </Box>
      <Text color={INK.ink3} wrap="truncate-end">{p.note}</Text>
    </Box>
  )
}

// Shares of a whole: one bar, then a legend with the numbers (so no share is only a colour).
export function Distribution(env: KitEnv, p: { key: string; parts: { label: string; value: number; tone: Tone | 'other' }[] }) {
  const { Box, Text } = env.el
  const total = Math.max(1, p.parts.reduce((a, b) => a + b.value, 0))
  return (
    <Box key={p.key} flexDirection="column" gap={0.5}>
      {env.surface === 'desktop' && (
        <Box flexDirection="row" height={0.5} gap={0.25}>
          {p.parts.map((x, i) => <Box key={i} width={pct((x.value / total) * 100)} height={0.5} backgroundColor={barHue(x.tone)} />)}
        </Box>
      )}
      <Box flexDirection="row" gap={2} flexWrap="wrap">
        {p.parts.map((x, i) => <Text key={i}><Text color={x.tone === 'other' || x.tone === 'neutral' ? INK.ink3 : TONE_TEXT[x.tone]}>■ </Text>{`${x.label} ${Math.round((x.value / total) * 100)}%`}</Text>)}
      </Box>
    </Box>
  )
}

const BARS = '▁▂▃▄▅▆▇█'

// A trend in one line of text. For a grid of coloured cells in the terminal, use a Raster.
export function Sparkline(env: KitEnv, p: { key: string; values: number[]; tone?: Tone }) {
  const { Text } = env.el
  const max = Math.max(1, ...p.values)
  const s = p.values.map(v => BARS[Math.min(7, Math.max(0, Math.round((v / max) * 7)))] ?? BARS[0]).join('')
  return <Text key={p.key} color={TONE_TEXT[p.tone ?? 'info']}>{s}</Text>
}
