// The gallery's Layouts tab: each layout filled with a small example, keyed lay-<name>.
import type { Kit } from '../kit'

export function Layouts(k: Kit) {
  const { Box, Text } = k.env.el
  const note = (text: string) => ({ do: 'note', text })
  return (
    <Box flexDirection="column" gap={2}>
      {k.Section({ key: 'h-overview', title: 'Overview', note: 'header · headline · focus · body · folded' })}
      {k.Overview({ key: 'lay-overview', headline: <Text bold>3 wait on you, 1 overdue</Text>,
        focus: k.Card({ key: 'lo-card', tone: 'you', title: 'For you', count: '1', children: k.Row({ id: 'lo-row', num: 104, name: 'Release notes', time: { text: '5h left', tone: 'you' } }) }),
        folded: [] })}
      {k.Section({ key: 'h-queue', title: 'Queue', note: 'header · table · footer' })}
      {k.Queue({ key: 'lay-queue', header: <Text bold>Everything open</Text>, table: k.Row({ id: 'lq-row', num: 101, name: 'Nightly backup check', time: { text: '1d left' } }),
        footer: k.Fold({ id: 'lq-more', hidden: 9, act: note('more') }) })}
      {k.Section({ key: 'h-detail', title: 'Detail', note: 'back · identity · facts · progress · next · sections' })}
      {k.Detail({ key: 'lay-detail', backBar: k.Button({ id: 'ld-back', label: '‹ Back', look: 'quiet', act: note('back') }), identity: <Text bold>Item 104 · Release notes</Text>,
        next: k.Next({ key: 'ld-next', text: 'Confirm the release date' }) })}
      {k.Section({ key: 'h-decision', title: 'Decision', note: 'context · question · evidence · choices' })}
      {k.DecisionLayout({ key: 'lay-decision', question: <Text bold>Publish draft 3?</Text>,
        choices: k.Button({ id: 'ldc-go', label: 'Publish', look: 'primary', act: note('publish') }) })}
      {k.Section({ key: 'h-states', title: 'States', note: 'empty · loading · failed' })}
      {k.States({ key: 'lay-states', empty: k.Empty({ key: 'ls-empty', title: 'Nothing open', text: 'Everything is done.' }) })}
    </Box>
  )
}
