// The gallery's Numbers tab: dashboard pieces, live pieces and charts.
import type { Kit } from '../kit'

export function Numbers(k: Kit, now: number) {
  const { Box } = k.env.el
  return (
    <Box flexDirection="column" gap={1}>
      {k.Section({ key: 'sec-stats', title: 'Numbers' })}
      {k.Metrics({ key: 'metrics', items: [{ value: '12', label: 'open' }, { value: '1', label: 'overdue', tone: 'alert' }, { value: '3', label: 'waiting on you', tone: 'you' }] })}
      {k.Stats({ key: 'stats', tiles: [
        k.StatTile({ key: 'st-open', value: '12', label: 'open', delta: { text: '▼ 3 this week', tone: 'ok' } }),
        k.StatTile({ key: 'st-time', value: '2.5h', label: 'to finish', delta: { text: '▲ 0.5h', tone: 'alert' } }),
        k.StatTile({ key: 'st-late', value: '1', label: 'overdue', tone: 'alert' }),
      ] })}
      {k.Meter({ key: 'm-disk', label: 'Disk', parts: [{ value: 6, tone: 'info' }, { value: 1, tone: 'alert' }], max: 10, cap: 8, note: '7 of 10 GB' })}
      {k.Meter({ key: 'm-empty', label: 'Queue', parts: [], max: 8, note: '0 waiting' })}
      {k.Meter({ key: 'm-third', label: 'Week', parts: [{ value: 1, tone: 'info' }], max: 3, note: '1 of 3' })}
      {k.Distribution({ key: 'dist-thirds', parts: [{ label: 'Mine', value: 1, tone: 'you' }, { label: 'Claude', value: 1, tone: 'claude' }, { label: 'Done', value: 1, tone: 'ok' }] })}
      {k.Sparkline({ key: 'spark', values: [0, 1, 2, 3, 5, 3, 4, 6, 7, 5, 6, 7] })}
      {k.Section({ key: 'sec-live', title: 'Live', note: 'moves on the desktop' })}
      {k.Live({ key: 'live-line', text: 'Reading the export and its log', since: now - 41_000 })}
      {k.Countdown({ key: 'live-countdown', until: now + (4 * 3600 + 59 * 60) * 1000, now })}
      {k.Ticker({ key: 'live-ticker', items: ['3 items wait on you', 'next due: item 104 in 5h', 'read at 09:30'], every: 3000 })}
      {k.StepBar({ key: 'stepbar', done: 3, total: 5, tone: 'claude' })}
      {k.Section({ key: 'sec-charts', title: 'Charts', note: 'pictures on the desktop, words elsewhere' })}
      {k.StepRail({ key: 'rail', steps: ['read', 'check', 'draft', 'review', 'save'], current: 2 })}
      {k.Ring({ key: 'ring', value: '5h', label: 'left', fraction: 0.8, tone: 'you' })}
    </Box>
  )
}
