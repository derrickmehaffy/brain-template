// Controls. Where the mod handed the kit its Clients (the desktop), each press is the kit's
// button Client; everywhere else it is the host's Button, whose press runs the act through
// env.perform. Either way the mod defines the act and validates it before running it.
import type { ButtonSpec, El, KitEnv, PressProps } from './types'
import { NEUTRAL, TONE_TEXT } from './tokens'

export function Button(env: KitEnv, s: ButtonSpec) {
  const look = s.look ?? 'secondary'
  if (env.clients) {
    // A Client's props must be plain data with no `undefined` anywhere in them, or the engine
    // refuses the whole tree: leave a missing badge or icon out rather than passing undefined.
    const props: PressProps = { id: s.id, label: s.label, look, act: s.act }
    if (s.badge) props.badge = s.badge
    if (s.icon) props.icon = true
    return env.clients.button(s.id, props)
  }
  const { Button: B } = env.el
  const text = s.badge ? `${s.label} (${s.badge})` : s.label
  const primary = look === 'primary' || look === 'attention' || look === 'selected'
  return <B key={s.id} label={text} variant={primary ? 'primary' : 'secondary'} dimColor={look === 'quiet'} onPress={() => env.perform(s.act)} />
}

// A one-glyph button for chrome, such as ↻ to refresh.
export function IconButton(env: KitEnv, s: ButtonSpec) {
  return Button(env, { ...s, look: s.look ?? 'quiet', icon: true })
}

type Item = { id: string; label: string; count?: number; act: ButtonSpec['act'] }

// Tabs: a segmented row. The open tab is filled, the rest are quiet.
export function Tabs(env: KitEnv, p: { key: string; items: Item[]; on: string }) {
  const { Box } = env.el
  const desk = env.surface === 'desktop'
  return (
    <Box key={p.key} flexDirection="row" gap={desk ? 0.25 : 1} alignSelf="flex-start"
      borderStyle={desk ? 'single' : undefined} borderColor={desk ? NEUTRAL.edge : undefined}
      backgroundColor={desk ? NEUTRAL.well : undefined} paddingX={desk ? 0.1 : 0} paddingY={desk ? 0.1 : 0}>
      {p.items.map(i => Button(env, { id: i.id, label: i.label, badge: i.count, look: i.id === p.on ? 'secondary' : 'quiet', act: i.act }))}
    </Box>
  )
}

// Filter chips: the chosen one tinted.
export function Chips(env: KitEnv, p: { key: string; items: Item[]; on: string }) {
  const { Box } = env.el
  return (
    <Box key={p.key} flexDirection="row" gap={1} flexWrap="wrap">
      {p.items.map(i => Button(env, { id: i.id, label: i.count === undefined ? i.label : `${i.label} ${i.count}`, look: i.id === p.on ? 'selected' : 'secondary', act: i.act }))}
    </Box>
  )
}

// A suggested request for Claude. Its act should fill the prompt (`$.prompt.fill`), never send
// it: the person reads it and presses Enter themselves.
export function PromptChip(env: KitEnv, p: { id: string; text: string; act: ButtonSpec['act'] }) {
  return Button(env, { id: p.id, label: `${p.text} ↵`, look: 'selected', act: p.act })
}

// A two-step confirm for an act that cannot be undone: the button turns into its own question.
// The mod keeps which confirm is open in its state.
export function Confirm(env: KitEnv, p: {
  id: string; label: string; question: string; open: boolean
  openAct: ButtonSpec['act']; yes: { label: string; act: ButtonSpec['act'] }; cancelAct: ButtonSpec['act']
}) {
  const { Box, Text } = env.el
  if (!p.open) return Button(env, { id: p.id, label: p.label, act: p.openAct })
  return (
    <Box key={`${p.id}-ask`} flexDirection="row" alignItems="center" gap={1} flexWrap="wrap">
      <Text color={TONE_TEXT.alert}>{p.question}</Text>
      {Button(env, { id: `${p.id}-yes`, label: p.yes.label, look: 'attention', act: p.yes.act })}
      {Button(env, { id: `${p.id}-cancel`, label: 'Cancel', look: 'quiet', act: p.cancelAct })}
    </Box>
  )
}

// "Show N more": a long list folds instead of scrolling forever.
export function Fold(env: KitEnv, p: { id: string; hidden: number; act: ButtonSpec['act'] }) {
  return Button(env, { id: p.id, label: `Show ${p.hidden} more`, look: 'quiet', act: p.act })
}

// Mobile draws no Input or Select (its element table hands back a stand-in that draws nothing),
// so the surface decides, not whether the element is in the table.
const takesInput = (env: KitEnv) => env.surface !== 'mobile'

// Typed text, with the host Input. Where there is none, a line says to type it in the chat.
export function Field(env: KitEnv, p: { key: string; label: string; placeholder: string; submitLabel: string; onSubmit: (v: string) => void }): El {
  const { Input, Text } = env.el
  if (!Input || !takesInput(env)) return <Text key={p.key} color="subtle">{`${p.label} (type it in the chat)`}</Text>
  return <Input key={p.key} label={p.label} placeholder={p.placeholder} submitLabel={p.submitLabel} onSubmit={(v: string) => p.onSubmit(v)} />
}

// Picking one of a few, with the host Select; plain text where there is none.
export function Picker(env: KitEnv, p: { key: string; label: string; value: string; options: { value: string; label: string }[]; onSelect: (v: string) => void }): El {
  const { Select, Text } = env.el
  if (!Select || !takesInput(env)) return <Text key={p.key}>{`${p.label}: ${p.value}`}</Text>
  return <Select key={p.key} label={p.label} value={p.value} options={p.options} onSelect={(v: string) => p.onSelect(v)} />
}
