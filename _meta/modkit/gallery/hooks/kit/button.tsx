// The kit's button on the desktop, drawn inside a Client.
//
// Why a Client: a Button the hooks module draws is pressed through a handle that belongs to one
// drawing, and on the desktop the click that gives a pane the keyboard also redraws it, so the
// first click into an unfocused pane could arrive with a stale handle and be dropped before any
// hook ran (seen on the desktop app in October 2026; recheck on newer builds before relying on
// it either way). A Client keeps its instance across redraws, and its posts are addressed by key.
//
// Why Box and Text, not a Button: inside a Client the desktop draws a Button as a plain label. So
// this draws the control itself, a rounded Box at the app's 24px control height, and takes the
// click from the pointer: down, then up inside the region, posts `{ kit: 1, act }` to the mod's
// ui.message hook. Return or Space does the same while the region has the focus.
import type { ClientSurface } from 'claude-code'

import { HUE, LOOKS, TONE_TEXT } from './tokens'
import type { PressProps } from './types'

type State = { hover: boolean; down: boolean }

// The newest props by instance: the listeners are set once and read these.
const latest = new WeakMap<object, PressProps>()

export default function Press(p: PressProps, surface: ClientSurface<State>) {
  const { Box, Text } = surface.elements
  latest.set(surface, p)
  if (surface.state === undefined) {
    const post = () => {
      const now = latest.get(surface)
      if (now) surface.post({ kit: 1, act: now.act })
    }
    surface.onPointer(e => {
      const s = surface.state ?? { hover: false, down: false }
      if (e.type === 'enter') surface.setState({ ...s, hover: true })
      else if (e.type === 'leave') surface.setState({ hover: false, down: false })
      else if (e.type === 'down' && e.button === 'left') surface.setState({ ...s, down: true })
      else if (e.type === 'up' && s.down) {
        surface.setState({ ...s, down: false })
        // A region not measured yet reports 0 columns: count the click rather than drop it.
        const inX = surface.columns === 0 || (e.x >= 0 && e.x < surface.columns)
        const inY = surface.rows === 0 || (e.y >= 0 && e.y < surface.rows)
        if (inX && inY) post()
      }
    })
    surface.onKey(k => {
      if (k.key === 'return' || k.key === ' ') post()
    })
    surface.setState({ hover: false, down: false })
  }
  const look = LOOKS[p.look] ?? LOOKS.secondary
  const hover = surface.state?.hover ?? false
  return (
    <Box flexDirection="row" alignItems="center" gap={1} borderStyle="single"
      borderColor={look.edge} backgroundColor={hover ? look.hover : look.fill}
      paddingX={p.icon ? 0.5 : 1} paddingY={0.08}>
      <Text color={look.ink}>{p.label}</Text>
      {p.badge ? <Text bold color={TONE_TEXT.you} backgroundColor={HUE.you + '2e'}>{` ${p.badge} `}</Text> : null}
    </Box>
  )
}
