import { expect, test } from 'claude-code/testing'

import { BAND, SURFACES, click, label, open, world } from './helpers'

test('/modkit opens the pane and draws cards and pills on both surfaces', async ($, on) => {
  const { opened } = world(on)
  for (const surface of SURFACES) {
    const ui = await open($, surface)
    expect(await ui.find({ type: 'Text', text: /^For Claude$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Saved the weekly summary/ })).toBeDefined()
    await ui.unmount()
  }
  expect(opened).toContain('brain-modkit')
})

test('a pill is a bracketed word in the terminal and a chip on the desktop', async ($, on) => {
  world(on)
  const term = await open($, 'terminal')
  expect(await term.find({ type: 'Text', text: '[failed]' })).toBeDefined()
  await term.unmount()
  const desk = await open($, 'desktop')
  expect(await desk.find({ type: 'Box', key: 'pill-alert' })).toBeDefined()
  await desk.unmount()
})

test('on the desktop a button is a Client, and a click posts its act', async ($, on) => {
  world(on)
  const ui = await open($, 'desktop')
  expect(await ui.find({ type: 'Client', key: 'btn-primary' })).toBeDefined()
  expect(await ui.find({ type: 'Button', key: 'btn-primary' })).toBeUndefined()
  await click(ui, 'btn-primary', 'desktop')
  expect(await ui.find({ type: 'Text', text: /Pressed: Primary/ })).toBeDefined()
  await ui.unmount()
})

test('in the terminal a button is the host Button, and its press runs the same act', async ($, on) => {
  world(on)
  const ui = await open($, 'terminal')
  expect(await label(ui, 'btn-primary', 'terminal')).toBe('Primary')
  await click(ui, 'btn-primary', 'terminal')
  expect(await ui.find({ type: 'Text', text: /Pressed: Primary/ })).toBeDefined()
  await ui.unmount()
})

test('a click lands even before the region has been measured', async ($, on) => {
  world(on)
  const ui = await open($, 'desktop')
  await click(ui, 'btn-secondary', 'desktop')
  expect(await ui.find({ type: 'Text', text: /Pressed: Secondary/ })).toBeDefined()
  await ui.unmount()
})

test('a post that is not a kit act, or names an act the mod does not know, does nothing', async ($, on) => {
  world(on)
  const ui = await open($, 'desktop')
  await ui.post({ act: { do: 'note', text: 'x' } }, { in: 'btn-primary' })
  await ui.post({ kit: 1, act: { do: 'shell', command: 'rm -rf /' } }, { in: 'btn-primary' })
  await ui.post({ kit: 1 }, { in: 'btn-primary' })
  expect(await ui.find({ type: 'Text', text: /Pressed/ })).toBeUndefined()
  await ui.unmount()
})

test('tabs switch on both surfaces', async ($, on) => {
  world(on)
  for (const surface of SURFACES) {
    const ui = await open($, surface)
    expect(await label(ui, 'tab-pieces', surface)).toBe('Pieces')
    await click(ui, 'tab-layouts', surface)
    expect(await ui.find({ type: 'Text', text: /^Buttons$/ })).toBeUndefined()
    await click(ui, 'tab-pieces', surface)
    expect(await ui.find({ type: 'Text', text: /^Buttons$/ })).toBeDefined()
    await ui.unmount()
  }
})

test('a two-step confirm asks in place, and Cancel puts the button back', async ($, on) => {
  world(on)
  for (const surface of SURFACES) {
    const ui = await open($, surface)
    await click(ui, 'confirm-delete', surface)
    expect(await ui.find({ type: 'Text', text: /Delete draft 3\?/ })).toBeDefined()
    await click(ui, 'confirm-delete-cancel', surface)
    expect(await ui.find({ type: 'Text', text: /Delete draft 3\?/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('a field and a picker reach the mod on both surfaces', async ($, on) => {
  world(on)
  for (const surface of SURFACES) {
    const ui = await open($, surface)
    await ui.input({ key: 'field-reason', text: 'moved to Friday' })
    expect(await ui.find({ type: 'Text', text: /Pressed: reason: moved to Friday/ })).toBeDefined()
    await ui.select({ key: 'picker-size', value: 'large' })
    expect(await ui.find({ type: 'Text', text: /Pressed: picked large/ })).toBeDefined()
    await ui.unmount()
  }
})

test('rows keep one column for times and one width for actions, and a long name truncates', async ($, on) => {
  world(on)
  const ui = await open($, 'desktop')
  for (const id of ['101', '103', '109']) {
    expect(await ui.find({ type: 'Box', key: `row-${id}-time` })).toBeDefined()
    expect(await ui.find({ type: 'Box', key: `row-${id}-action` })).toBeDefined()
  }
  expect(JSON.stringify(await ui.drawn())).toContain('"wrap":"truncate-end"')
  await ui.unmount()
})

test('a 30-column pane still draws its sections and rows', async ($, on) => {
  world(on)
  const ui = await open($, 'terminal', 30)
  expect(await ui.find({ type: 'Text', text: /^Buttons$/ })).toBeDefined()
  expect(await label(ui, 'row-101-act', 'terminal')).toBe('Start')
  await ui.unmount()
})

test('the numbers tab draws on both surfaces, and live pieces are Clients only on the desktop', async ($, on) => {
  world(on)
  for (const surface of SURFACES) {
    const ui = await open($, surface)
    await click(ui, 'tab-numbers', surface)
    for (const text of [/^12$/, /to finish/, /7 of 10 GB/, /Claude 33%/, /▁▂▃/]) {
      expect(await ui.find({ type: 'Text', text })).toBeDefined()
    }
    const client = await ui.find({ type: 'Client', key: 'live-line' })
    if (surface === 'desktop') expect(client).toBeDefined()
    else {
      expect(client).toBeUndefined()
      expect(await ui.find({ type: 'Text', text: /Reading the export/ })).toBeDefined()
    }
    await ui.unmount()
  }
})

test('the ticker moves on with the clock', async ($, on) => {
  world(on)
  const ui = await open($, 'desktop')
  await click(ui, 'tab-numbers', 'desktop')
  expect(await ui.find({ type: 'Text', in: 'live-ticker', text: /3 items wait on you/ })).toBeDefined()
  await ui.advance(3100)
  expect(await ui.find({ type: 'Text', in: 'live-ticker', text: /next due/ })).toBeDefined()
  await ui.unmount()
})

test('charts are plain Svg pictures on the desktop, never frames, and words in the terminal', async ($, on) => {
  world(on)
  const desk = await open($, 'desktop')
  await click(desk, 'tab-numbers', 'desktop')
  const drawn = JSON.stringify(await desk.drawn())
  expect(drawn).toContain('"type":"Svg"')
  expect(drawn).toContain('Step 3 of 5: draft')
  expect(drawn).not.toContain('"isInteractive":true')
  await desk.unmount()
  const term = await open($, 'terminal')
  await click(term, 'tab-numbers', 'terminal')
  expect(await term.find({ type: 'Svg' })).toBeUndefined()
  expect(await term.find({ type: 'Text', text: /▸ draft/ })).toBeDefined()
  await term.unmount()
})

test('a bar a third full draws, and the pane with it: every percentage is whole', async ($, on) => {
  world(on)
  const ui = await open($, 'desktop')
  await click(ui, 'tab-numbers', 'desktop')
  expect(JSON.stringify(await ui.drawn())).not.toMatch(/"width":"\d+\.\d+%"/)
  expect(await ui.find({ type: 'Text', text: /1 of 3/ })).toBeDefined()
  await ui.unmount()
})

test('every layout draws its zones, and an empty zone takes no room', async ($, on) => {
  world(on)
  for (const surface of SURFACES) {
    const ui = await open($, surface)
    await click(ui, 'tab-layouts', surface)
    for (const key of ['lay-overview', 'lay-queue', 'lay-detail', 'lay-decision', 'lay-states']) {
      expect(await ui.find({ type: 'Box', key })).toBeDefined()
    }
    expect(await ui.find({ type: 'Box', key: 'lay-overview-folded' })).toBeUndefined()
    await ui.unmount()
  }
})

test('each band layout draws in the band, and Off gives the band back', async ($, on) => {
  world(on)
  for (const surface of SURFACES) {
    const ui = await open($, surface)
    await click(ui, 'tab-band', surface)
    for (const [key, text] of [['band-show-working', /Item 104/], ['band-show-decision', /Draft 3 is ready/]] as const) {
      await click(ui, key, surface)
      const b = await $.ui.mount({ plugin: 'brain-modkit', surface, ...BAND })
      expect(await b.find({ type: 'Text', text })).toBeDefined()
      await b.unmount()
    }
    await click(ui, 'band-show-off', surface)
    const b = await $.ui.mount({ plugin: 'brain-modkit', surface, ...BAND })
    expect(await b.find({ type: 'Box', key: 'engine-band' })).toBeDefined()
    await b.unmount()
    await ui.unmount()
  }
})

test('only an https or http address becomes a link', async ($, on) => {
  world(on)
  for (const surface of SURFACES) {
    const ui = await open($, surface)
    expect(await ui.find({ type: 'Link', text: 'the guide' })).toBeDefined()
    expect(await ui.find({ type: 'Link', text: 'a local file' })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /^a local file$/ })).toBeDefined()
    await ui.unmount()
  }
})

// VS Code has no Client, and mobile has no Input, Select or Client: the kit falls back on both.
test('the pieces draw in VS Code and on mobile too', async ($, on) => {
  world(on)
  for (const surface of ['vscode', 'mobile'] as const) {
    await $.session.start({ cwd: '/w', surface, isInteractive: true })
    const ui = await $.ui.mount({ plugin: 'brain-modkit', surface, component: 'Pane', requestId: 'brain-modkit',
      props: { title: 'Mod kit', isFocused: true, bodyColumns: 50, placement: 'dock', scroll: { offset: 0, bodyRows: 80 }, view: {} } })
    expect(await ui.find({ type: 'Text', text: /^For Claude$/ })).toBeDefined()
    expect(await ui.find({ type: 'Client' })).toBeUndefined()
    if (surface === 'mobile') expect(await ui.find({ type: 'Text', text: /Reason \(type it in the chat\)/ })).toBeDefined()
    await ui.unmount()
  }
})
