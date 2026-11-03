// Rows, lists and tables. The alignment rules live here: in a list every action takes
// COLUMN.action characters and every time COLUMN.time, so both line up down the list, and a long
// name truncates rather than pushing them out of line.
import type { ButtonSpec, El, KitEnv, Tone } from './types'
import { COLUMN, HUE, INK, NEUTRAL, TONE_TEXT, tint } from './tokens'
import { Button } from './controls'

export type RowProps = {
  id: string
  num?: string | number
  name: string
  pills?: El[]
  time?: { text: string; tone?: Tone }
  status?: { text: string; tone: Tone }
  action?: ButtonSpec
  open?: ButtonSpec['act']
  dim?: boolean
  selected?: boolean
}

export function Row(env: KitEnv, p: RowProps) {
  const { Box, Text } = env.el
  const desk = env.surface === 'desktop'
  const openBtn = p.open !== undefined && Button(env, { id: `${p.id}-open`, label: 'Open', look: 'quiet', act: p.open })
  return (
    <Box key={p.id} flexDirection="row" justifyContent="space-between" alignItems="center" gap={2}
      paddingX={1} marginX={-1} backgroundColor={p.selected ? tint('claude') : undefined}
      hover={desk ? { backgroundColor: p.selected ? HUE.claude + '33' : NEUTRAL.rowHover } : undefined}>
      <Box flexDirection="row" alignItems="center" gap={1} flexShrink={1} minWidth={0}>
        {p.num !== undefined && <Text bold dimColor={p.dim}>{String(p.num)}</Text>}
        <Text wrap="truncate-end" dimColor={p.dim}>{p.name}</Text>
        {p.pills}
      </Box>
      <Box flexDirection="row" alignItems="center" gap={1} flexShrink={0}>
        {openBtn && (desk ? <Box display="none" hover={{ display: 'flex' }}>{openBtn}</Box> : openBtn)}
        {p.status && <Box key={`${p.id}-status`} width={COLUMN.status}><Text color={TONE_TEXT[p.status.tone]}>{p.status.text}</Text></Box>}
        {p.time && <Box key={`${p.id}-time`} width={COLUMN.time} justifyContent="flex-end"><Text color={p.time.tone && p.time.tone !== 'neutral' ? TONE_TEXT[p.time.tone] : INK.ink3}>{p.time.text}</Text></Box>}
        {p.action && <Box key={`${p.id}-action`} width={COLUMN.action} justifyContent="flex-end">{Button(env, { ...p.action, id: `${p.id}-act` })}</Box>}
      </Box>
    </Box>
  )
}

export function List(env: KitEnv, p: { key: string; children: El[] }) {
  const { Box } = env.el
  return <Box key={p.key} flexDirection="column">{p.children}</Box>
}

type Column = { key: string; label: string; width: number | 'grow'; align?: 'left' | 'right' }

// A table: fixed widths in characters, one column may grow, and every cell truncates rather
// than pushing its neighbours.
export function Table(env: KitEnv, p: { key: string; columns: Column[]; rows: { id: string; cells: Record<string, El | string> }[] }) {
  const { Box, Text } = env.el
  const cell = (c: Column, v: El | string, head = false) => (
    <Box key={c.key} width={c.width === 'grow' ? undefined : c.width} flexGrow={c.width === 'grow' ? 1 : 0} flexShrink={c.width === 'grow' ? 1 : 0}
      minWidth={0} overflow="hidden" justifyContent={c.align === 'right' ? 'flex-end' : 'flex-start'}>
      {typeof v === 'string' ? <Text wrap="truncate-end" color={head ? INK.ink3 : undefined}>{v}</Text> : v}
    </Box>
  )
  return (
    <Box key={p.key} flexDirection="column">
      <Box flexDirection="row" gap={1}>{p.columns.map(c => cell(c, c.label, true))}</Box>
      {p.rows.map(r => (
        <Box key={r.id} flexDirection="row" gap={1} alignItems="center" paddingX={1} marginX={-1}
          hover={env.surface === 'desktop' ? { backgroundColor: NEUTRAL.rowHover } : undefined}>
          {p.columns.map(c => cell(c, r.cells[c.key] ?? ''))}
        </Box>
      ))}
    </Box>
  )
}
