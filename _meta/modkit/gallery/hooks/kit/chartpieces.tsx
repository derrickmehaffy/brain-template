// Charts: an Svg where the surface has one, words everywhere else. Every picture's alt says what
// it shows, so a number is never only in the drawing.
//
// Never pass `isInteractive`. An interactive Svg is drawn in a sandboxed frame of its own, loaded
// lazily, and frames in a scrolling pane repaint as it scrolls, so charts flashed (seen on the
// desktop app in October 2026). A plain Svg is an image whose CSS animations still play.
import type { KitEnv, Tone } from './types'
import { GLYPH, INK, TONE_TEXT } from './tokens'
import { ring, stepRail } from './charts'

// A character is about 7.6 CSS pixels wide in the desktop's pane font.
const PX = 7.6

const svgOf = (env: KitEnv) => (env.surface === 'desktop' || env.surface === 'vscode' ? env.el.Svg : undefined)

export function StepRail(env: KitEnv, p: { key: string; steps: string[]; current: number; tone?: Tone }) {
  const { Text } = env.el
  const Svg = svgOf(env)
  const alt = `Step ${p.current + 1} of ${p.steps.length}: ${p.steps[p.current] ?? ''}`
  if (Svg) return <Svg key={p.key} alt={alt} height={46} source={stepRail({ steps: p.steps, current: p.current, tone: p.tone ?? 'claude', width: Math.round(env.width * PX) })} />
  return (
    <Text key={p.key}>
      {p.steps.map((s, i) => (
        <Text key={i} bold={i === p.current} color={i < p.current ? TONE_TEXT.ok : i === p.current ? TONE_TEXT[p.tone ?? 'claude'] : INK.ink3}>
          {`${i > 0 ? ' › ' : ''}${i < p.current ? GLYPH.done : i === p.current ? GLYPH.now : GLYPH.todo} ${s}`}
        </Text>
      ))}
    </Text>
  )
}

export function Ring(env: KitEnv, p: { key: string; value: string; label: string; fraction: number; tone: Tone }) {
  const { Text } = env.el
  const Svg = svgOf(env)
  if (Svg) return <Svg key={p.key} alt={`${p.value} ${p.label}`} width={64} height={64} source={ring(p)} />
  return <Text key={p.key} color={TONE_TEXT[p.tone]}>{`${p.value} ${p.label}`}</Text>
}
