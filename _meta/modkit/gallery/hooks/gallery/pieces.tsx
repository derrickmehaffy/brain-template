// The gallery's Pieces tab: one of each control and content piece, with made-up data. The tests
// find pieces by the keys used here.
import type { Kit } from '../kit'
import { ITEMS, LONG } from './samples'

export function Pieces(k: Kit, s: { confirming: string | null; chip: string }) {
  const { Box, Text } = k.env.el
  const note = (text: string) => ({ do: 'note', text })
  return (
    <Box flexDirection="column" gap={1}>
      {k.Section({ key: 'sec-buttons', title: 'Buttons', note: 'one primary per view' })}
      <Box flexDirection="row" gap={1} flexWrap="wrap">
        {k.Button({ id: 'btn-primary', label: 'Primary', look: 'primary', act: note('Primary') })}
        {k.Button({ id: 'btn-secondary', label: 'Secondary', act: note('Secondary') })}
        {k.Button({ id: 'btn-attention', label: 'Needs you', look: 'attention', act: note('Needs you') })}
        {k.Button({ id: 'btn-quiet', label: 'Quiet', look: 'quiet', act: note('Quiet') })}
        {k.IconButton({ id: 'btn-icon', label: '↻', act: note('Refresh') })}
        {k.Button({ id: 'btn-badge', label: 'Inbox', badge: 2, act: note('Inbox') })}
      </Box>
      {k.Section({ key: 'sec-controls', title: 'More controls' })}
      {k.Chips({ key: 'chips', on: `chip-${s.chip}`, items: [
        { id: 'chip-all', label: 'All', count: 12, act: { do: 'chip', id: 'all' } },
        { id: 'chip-mine', label: 'Mine', count: 4, act: { do: 'chip', id: 'mine' } },
        { id: 'chip-overdue', label: 'Overdue', count: 1, act: { do: 'chip', id: 'overdue' } },
      ] })}
      <Text color="subtle">{`Showing: ${s.chip}`}</Text>
      <Box flexDirection="row" gap={1} flexWrap="wrap" alignItems="center">
        {k.PromptChip({ id: 'prompt-retro', text: 'run a retro on that', act: note('would fill: run a retro on that') })}
        {k.Fold({ id: 'fold-more', hidden: 3, act: note('Show 3 more') })}
      </Box>
      {k.Confirm({ id: 'confirm-delete', label: 'Delete the draft', question: 'Delete draft 3?', open: s.confirming === 'confirm-delete',
        openAct: { do: 'confirm', id: 'confirm-delete' }, yes: { label: 'Yes, delete', act: note('deleted draft 3') },
        cancelAct: { do: 'confirm', id: null } })}
      {k.Field({ key: 'field-reason', label: 'Reason', placeholder: 'Why it moves', submitLabel: 'Save',
        onSubmit: v => k.env.perform(note(`reason: ${v.slice(0, 60)}`)) })}
      {k.Picker({ key: 'picker-size', label: 'Size', value: 'small', options: [{ value: 'small', label: 'Small' }, { value: 'large', label: 'Large' }],
        onSelect: v => k.env.perform(note(`picked ${v}`)) })}

      {k.Section({ key: 'sec-content', title: 'Cards and pills', note: 'tinted for what needs attention' })}
      {k.Card({ key: 'card-claude', tone: 'claude', title: 'For Claude', count: '2', children: <Text color="subtle">Claude's work</Text> })}
      {k.Card({ key: 'card-you', tone: 'you', title: 'For you', count: '3', children: <Text color="subtle">waits on you</Text> })}
      {k.Card({ key: 'card-neutral', tone: 'neutral', title: 'Neutral', children: <Text color="subtle">plain content</Text> })}
      <Box flexDirection="row" gap={1} flexWrap="wrap">
        {k.Pill({ key: 'pill-claude', tone: 'claude', text: 'Claude' })}
        {k.Pill({ key: 'pill-you', tone: 'you', text: 'yours' })}
        {k.Pill({ key: 'pill-ok', tone: 'ok', text: 'done' })}
        {k.Pill({ key: 'pill-alert', tone: 'alert', text: 'failed' })}
        {k.Pill({ key: 'pill-info', tone: 'info', text: 'next' })}
      </Box>
      {k.Notice({ key: 'notice-ok', tone: 'ok', text: 'Saved the weekly summary.' })}

      {k.Section({ key: 'sec-rows', title: 'Rows', note: 'times and actions line up' })}
      {k.List({ key: 'rows', children: [...ITEMS, LONG].map(t => k.Row({
        id: `row-${t.id}`, num: t.id, name: t.name,
        pills: t.tone === 'alert' ? [k.Pill({ key: `row-${t.id}-pill`, tone: 'alert', text: 'overdue' })] : [],
        time: { text: t.time, tone: t.tone }, open: note(`open ${t.id}`),
        action: { id: `row-${t.id}-act`, label: 'Start', act: note(`start ${t.id}`) },
      })) })}
      {k.Section({ key: 'sec-table', title: 'Table' })}
      {k.Table({ key: 'table', columns: [
        { key: 'id', label: '#', width: 5 }, { key: 'name', label: 'Item', width: 'grow' },
        { key: 'age', label: 'Age', width: 4 }, { key: 'state', label: 'State', width: 9 },
        { key: 'act', label: '', width: 14, align: 'right' },
      ], rows: ITEMS.map(t => ({ id: `tr-${t.id}`, cells: {
        id: String(t.id), name: t.name, age: t.age, state: t.state,
        act: k.Button({ id: `tr-${t.id}-open`, label: 'Open', look: 'quiet', act: note(`open ${t.id}`) }),
      } })) })}
      {k.KeyValue({ key: 'kv', pairs: [['Owner', 'you'], ['Checked', 'this morning'], ['Source', 'the weekly export']] })}

      {k.Section({ key: 'sec-working', title: 'Working on something' })}
      {k.Banner({ key: 'banner', tone: 'alert', text: 'The nightly export failed at 02:10.', action: { id: 'banner-show', label: 'Show it', act: note('show the failed run') } })}
      {k.Next({ key: 'next', text: 'Read the export log, then rerun it', reason: 'Nothing else is waiting.' })}
      {k.Decision({ key: 'decision', context: 'Draft 3 · release notes', question: 'Draft 3 is ready to review.', evidence: '212 words, 2 links, one open question about the date.',
        choices: [k.Button({ id: 'dec-review', label: 'Review', look: 'primary', act: note('Review') }), k.Button({ id: 'dec-later', label: 'Later', look: 'quiet', act: note('Later') })] })}
      {k.Empty({ key: 'empty', title: 'Nothing in progress', text: 'Pick an item above, or type', command: 'start item 104' })}
      {k.Loading({ key: 'loading', label: 'Reading the export…', lines: [70, 90, 55] })}
      {k.Failed({ key: 'failed', text: 'The read failed: the file was not there. Showing the last good copy.', retry: { id: 'failed-retry', label: 'Try again', act: note('retry') } })}
      {k.Timeline({ key: 'timeline', events: [{ at: 'Mon 09:00', text: 'You asked for a summary', who: 'you' }, { at: 'Mon 09:04', text: 'Claude wrote draft 1', who: 'claude' }, { at: 'now', text: 'Waiting on you', who: 'none' }] })}
      {k.Checklist({ key: 'checks', items: [{ label: 'Inputs read', note: 'clean', state: 'done', by: '4s' }, { label: 'Summary', note: 'running', state: 'running' }, { label: 'Translation', note: 'not needed: English only', state: 'na' }, { label: 'Review', state: 'todo' }] })}
      {k.Section({ key: 'sec-links', title: 'Links', note: 'https only' })}
      <Box flexDirection="row" gap={2} alignItems="center" flexWrap="wrap">
        {k.Link({ key: 'link-web', href: 'https://example.com/guide', label: 'the guide' })}
        {k.Link({ key: 'link-local', href: 'file:///etc/hosts', label: 'a local file' })}
      </Box>
      {k.Prose({ key: 'prose', text: 'The steps are in [the guide](https://example.com/guide); the rest is below.' })}
    </Box>
  )
}
