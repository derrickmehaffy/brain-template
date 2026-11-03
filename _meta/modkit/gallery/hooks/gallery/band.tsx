// The gallery's Band tab, and the band above the prompt while one is chosen there.
import type { Kit } from '../kit'
import type { BandShown } from '../../types'

export function BandTab(k: Kit) {
  const { Box, Text } = k.env.el
  return (
    <Box flexDirection="column" gap={1}>
      <Text color="subtle">Draws each band layout in the band above the prompt.</Text>
      <Box flexDirection="row" gap={1} flexWrap="wrap">
        {k.Button({ id: 'band-show-idle', label: 'Idle', act: { do: 'band', state: 'idle' } })}
        {k.Button({ id: 'band-show-working', label: 'Working', act: { do: 'band', state: 'working' } })}
        {k.Button({ id: 'band-show-decision', label: 'Something waits', act: { do: 'band', state: 'decision' } })}
        {k.Button({ id: 'band-show-off', label: 'Off', look: 'quiet', act: { do: 'band', state: null } })}
      </Box>
    </Box>
  )
}

export function BandView(k: Kit, shown: BandShown, now: number) {
  const shortcuts = [
    k.Button({ id: 'bd-inbox', label: 'Inbox', badge: shown === 'decision' ? 2 : undefined, act: { do: 'note', text: 'Inbox' } }),
    k.IconButton({ id: 'bd-refresh', label: '↻', act: { do: 'note', text: 'Refresh' } }),
  ]
  if (shown === 'working') return k.BandWorking({ shortcuts, label: 'Item 104', live: k.Live({ key: 'bd-live', text: 'Drafting the release notes', since: now - 12_000 }) })
  if (shown === 'decision') return k.BandDecision({ question: 'Draft 3 is ready', note: '· 212 words', actions: [k.Button({ id: 'bd-review', label: 'Review', look: 'primary', act: { do: 'note', text: 'Review' } })] })
  return k.BandIdle({ shortcuts, ticker: k.Ticker({ key: 'bd-ticker', items: ['next due: item 104 in 5h', '3 items wait on you', 'read at 09:30'] }) })
}
