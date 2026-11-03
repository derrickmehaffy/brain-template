// Charts as SVG text, for the Svg element (desktop and VS Code). An Svg is drawn as an image: it
// cannot see the app's theme tokens, so each chart carries a light and a dark palette of its own
// and picks one with prefers-color-scheme. Its CSS animations play, and stop for reduced motion.
import type { Tone } from './types'

export const C = { claude: '#7161e0', you: '#db9300', ok: '#009300', alert: '#d03b3b', info: '#2a78d6', idle: '#898781' } as const

const hue = (t: Tone) => (t === 'neutral' ? C.idle : C[t])

const FONT = '-apple-system, "Segoe UI", system-ui, sans-serif'

// Text from the mod goes into the SVG escaped, always.
export function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function head(w: number, height: number): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${height}" width="${w}" height="${height}" font-family='${FONT}'>` +
    '<style>.t{fill:#f5f4ef}.s{fill:#c3c2b7}.f{fill:#898781}.ln{stroke:rgba(255,255,255,.2)}.bg{fill:#1a1a19}' +
    '@media (prefers-color-scheme: light){.t{fill:#0b0b0b}.s{fill:#52514e}.ln{stroke:rgba(11,11,11,.2)}.bg{fill:#ffffff}}' +
    '.pulse{transform-box:fill-box;transform-origin:center;animation:pulse 1.8s ease-out infinite}' +
    '@keyframes pulse{0%{transform:scale(1);opacity:.6}100%{transform:scale(2.6);opacity:0}}' +
    '@media (prefers-reduced-motion: reduce){.pulse{animation:none}}</style>'
}

// Steps along a rail: done steps filled, the current one pulsing, the rest hollow.
export function stepRail(p: { steps: string[]; current: number; tone: Tone; width: number }): string {
  const W = Math.max(320, Math.round(p.width))
  const n = Math.max(2, p.steps.length)
  const x = (i: number) => Math.round(24 + ((W - 48) * i) / (n - 1))
  const c = hue(p.tone)
  let s = head(W, 46) + `<line x1="24" y1="14" x2="${W - 24}" y2="14" class="ln" stroke-width="4" stroke-linecap="round"/>`
  if (p.current > 0) s += `<line x1="24" y1="14" x2="${x(Math.min(p.current, n - 1))}" y2="14" stroke="${c}" stroke-width="4" stroke-linecap="round"/>`
  p.steps.forEach((label, i) => {
    if (i < p.current) s += `<circle cx="${x(i)}" cy="14" r="6" fill="${c}"/>`
    else if (i === p.current) s += `<circle class="pulse" cx="${x(i)}" cy="14" r="7" fill="${c}"/><circle cx="${x(i)}" cy="14" r="7" class="bg" stroke="${c}" stroke-width="3"/>`
    else s += `<circle cx="${x(i)}" cy="14" r="6" class="bg ln" stroke-width="2"/>`
    const cls = i === p.current ? 't' : i < p.current ? 's' : 'f'
    s += `<text x="${x(i)}" y="40" font-size="11" text-anchor="middle" class="${cls}"${i === p.current ? ' font-weight="600"' : ''}>${esc(label)}</text>`
  })
  return s + '</svg>'
}

// One number that matters, in a ring filled to `fraction`.
export function ring(p: { value: string; label: string; fraction: number; tone: Tone }): string {
  const dash = Math.round(195 * Math.max(0, Math.min(1, p.fraction)))
  return head(76, 76) +
    `<circle cx="38" cy="38" r="31" fill="none" class="ln" stroke-width="7"/>` +
    `<circle cx="38" cy="38" r="31" fill="none" stroke="${hue(p.tone)}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${dash} 195" transform="rotate(-90 38 38)"/>` +
    `<text x="38" y="38" font-size="15" font-weight="600" text-anchor="middle" class="t">${esc(p.value)}</text>` +
    `<text x="38" y="52" font-size="10" text-anchor="middle" class="f">${esc(p.label)}</text></svg>`
}
