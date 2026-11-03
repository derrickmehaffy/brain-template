// The kit's shared types. Nothing here touches `$`: a mod's entry file builds a KitEnv once
// per drawing, and every piece is a plain function of that env and its own props.
import type { JsonValue } from 'claude-code'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type El = any

// The element table a surface hands a ui.render hook: `$.ui.resolve(e)`. Only Box, Text and
// Button are on every surface; the rest are looked up before use and fall back to text.
export type Elements = {
  Box: El
  Text: El
  Button: El
  Code?: El
  Markdown?: El
  Link?: El
  Input?: El
  Select?: El
  Svg?: El
}

// What a colour means. A tone never travels alone: every piece pairs it with a glyph or a word.
//   claude   Claude is doing it, or did it
//   you      it waits on the person
//   ok       done, healthy, nothing to do
//   alert    failed, blocked, overdue
//   info     what comes next, or what is selected
//   neutral  anything else
export type Tone = 'claude' | 'you' | 'ok' | 'alert' | 'info' | 'neutral'

// How a button looks. `link` is accent-coloured text with no box, for a name that opens a view.
export type Look = 'primary' | 'secondary' | 'attention' | 'quiet' | 'selected' | 'link'

// A button. `act` is plain data the mod defines and validates; the kit carries it untouched.
export type ButtonSpec = { id: string; label: string; look?: Look; act: JsonValue; badge?: number; icon?: boolean }

// Props of the two Client modules. The mod's entry file builds them with literal module paths.
export type PressProps = { id: string; label: string; look: Look; act: JsonValue; badge?: number; icon?: boolean }
export type MotionProps =
  | { kind: 'live'; text: string; since: number | null; tone: Tone }
  | { kind: 'countdown'; until: number; soonHours: number }
  | { kind: 'ticker'; items: string[]; every: number }

export type Clients = {
  button: (key: string, props: PressProps) => El
  motion: (key: string, props: MotionProps) => El
}

export type KitEnv = {
  el: Elements
  // e.surface: 'terminal' | 'desktop' | 'vscode' | 'mobile'
  surface: string
  // the pane's or band's body width in characters (e.props.bodyColumns)
  width: number
  // the mod's Client factories, where the surface has Clients and the mod wants them
  clients?: Clients
  // runs an act directly, for the host Buttons drawn where there are no Clients
  perform: (act: JsonValue) => void
}
