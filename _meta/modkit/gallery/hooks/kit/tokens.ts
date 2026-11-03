// The kit's tokens. Text and lines use Claude Code's theme colour names, which every surface maps
// to its own palette, so light and dark follow the app. Hex appears in two places only: the tints
// below (one hue per tone at a low alpha, which reads on light and dark alike) and the charts.
import type { Look, Tone } from './types'

export const INK = {
  ink: 'text',
  ink2: 'inactive',
  ink3: 'subtle',
  line: 'promptBorderShimmer',
  lineStrong: 'promptBorder',
  surface: 'userMessageBackground',
} as const

export const TONE_TEXT: Record<Tone, string> = {
  claude: 'autoAccept',
  you: 'warning',
  ok: 'success',
  alert: 'error',
  info: 'suggestion',
  neutral: 'inactive',
}

export const HUE: Record<Exclude<Tone, 'neutral'>, string> = {
  claude: '#7161e0',
  you: '#a66a00',
  ok: '#009300',
  alert: '#d03b3b',
  info: '#2a78d6',
}

// Two hex digits of alpha: a fill and an edge.
const FILL = '21'
const EDGE = '73'

export const NEUTRAL = {
  fill: '#80808014', fillHover: '#80808026', edge: '#80808033', track: '#80808026', none: '#00000000',
  // a segmented control's well, and a row under the pointer
  well: '#8080800d', rowHover: '#8080801a',
  // a meter's threshold mark, and a bar segment that counts but carries no tone
  mark: '#89878199', bar: '#8080806b',
}

export function tint(t: Tone): string | undefined {
  return t === 'neutral' ? undefined : HUE[t] + FILL
}

export function edge(t: Tone): string {
  return t === 'neutral' ? NEUTRAL.edge : HUE[t] + EDGE
}

// Status glyphs. Colour is never the only signal: each tone is drawn with one of these or a word.
export const GLYPH = { done: '✓', now: '▸', todo: '·', working: '●', idle: '○', needs: '!', failed: '✗', na: '–' } as const

// A button's colours by look.
export const LOOKS: Record<Look, { fill: string; hover: string; edge: string; ink: string }> = {
  primary: { fill: HUE.claude + FILL, hover: HUE.claude + '33', edge: HUE.claude + EDGE, ink: INK.ink },
  secondary: { fill: NEUTRAL.fill, hover: NEUTRAL.fillHover, edge: NEUTRAL.edge, ink: INK.ink },
  attention: { fill: HUE.you + FILL, hover: HUE.you + '33', edge: HUE.you + '80', ink: INK.ink },
  quiet: { fill: NEUTRAL.none, hover: NEUTRAL.fill, edge: NEUTRAL.none, ink: INK.ink3 },
  selected: { fill: HUE.info + FILL, hover: HUE.info + '33', edge: HUE.info + EDGE, ink: TONE_TEXT.info },
  link: { fill: NEUTRAL.none, hover: NEUTRAL.fill, edge: NEUTRAL.none, ink: TONE_TEXT.info },
}

// Column widths in characters, so actions and times line up down a list.
export const COLUMN = { action: 14, time: 9, status: 16, key: 14 } as const

// A width as a percentage the engine accepts: a whole number. A fractional percentage (a third)
// refuses the whole drawing, not just the bar, so every % width goes through here.
export function pct(n: number): string {
  return `${Math.max(0, Math.min(100, Math.round(Number.isFinite(n) ? n : 0)))}%`
}
