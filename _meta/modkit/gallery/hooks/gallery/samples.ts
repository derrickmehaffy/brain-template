// Made-up data the gallery draws. Keep it invented: never a real person, system or record.
export const ITEMS = [
  { id: 101, name: 'Nightly backup check', time: '1d left', tone: 'neutral' as const, age: '2d', state: 'open' },
  { id: 102, name: 'Garden planting plan', time: '2d left', tone: 'neutral' as const, age: '5d', state: 'open' },
  { id: 103, name: 'Certificate renewal', time: '3d over', tone: 'alert' as const, age: '9d', state: 'overdue' },
  { id: 104, name: 'Release notes', time: '5h left', tone: 'you' as const, age: '1d', state: 'yours' },
]

export const LONG = { id: 109, name: 'A very long item name that has to truncate before it pushes the time and the action out of line', time: '6h left', tone: 'you' as const, age: '1d', state: 'yours' }
