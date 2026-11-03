import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { attention, parse, summary } from '../hooks/health'

// What the health check prints, made up: one check to look at, two fine.
const DOCTOR = [
  'ok     tools: git, python3 found',
  'WARN   git: 3 uncommitted changes; brain-sync commits them',
  'ok     lint: no broken skill',
  'doctor: 0 block, 1 warn',
].join('\n')
const HEALTHY = 'ok     tools: git, python3 found\ndoctor: 0 block, 0 warn\n'

const PANE = {
  plugin: 'modkit-starter', component: 'Pane', requestId: 'modkit-starter',
  props: { title: 'Health', isFocused: true, bodyColumns: 64, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} },
} as const
const BAND = {
  plugin: 'modkit-starter', component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 90, scroll: { offset: 0, bodyRows: 6 }, view: {} },
} as const
const SURFACES = ['terminal', 'desktop'] as const

// Everything the engine would answer beneath the mod. `stdout` is what the health check prints;
// `fails` makes the run itself fail.
function world(on: On, stdout: string, fails = false) {
  const ran: string[][] = []
  const filled: string[] = []
  const submitted: string[] = []
  const status: (string | undefined)[] = []
  mock.clock(on, { now: Date.parse('2026-11-02T09:30:00Z') })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.status', ($, e) => { status.push(e.text); return { value: undefined } })
  on('process.run', ($, e) => {
    ran.push([...e.argv])
    if (fails) return { deny: 'no such file' }
    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('prompt.fill', ($, e) => { filled.push(e.text); return { isFilled: true } })
  on('prompt.submit', ($, e) => { submitted.push(e.text); return {} })
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => $.ui.resolve(e).Box({ key: 'engine-band' }))
  return { ran, filled, submitted, status }
}

const RUN = { command: 'modkit-starter', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } } as const

// Starts the session, then runs the command, which waits for the reading session.start began.
async function start($: Parameters<Parameters<typeof test>[1]>[0], surface: 'terminal' | 'desktop' = 'terminal') {
  await $.session.start({ cwd: '/brain', surface, isInteractive: true })
  return $.command.run({ ...RUN, args: '' })
}

test('the health check output is parsed, worst first', () => {
  const found = parse(DOCTOR + '\nBLOCK  hook: not installed\nnoise line\n')
  expect(found.length).toBe(4)
  expect(attention(found).map(f => f.level)).toEqual(['block', 'warn'])
  expect(summary(found)).toBe('1 blocking, 1 to look at')
  expect(summary(parse(HEALTHY))).toBe('all 1 checks ok')
})

test('at session start it runs the read-only health check, and the band says what needs attention', async ($, on) => {
  const { ran, status } = world(on, DOCTOR)
  await start($)
  expect(ran).toEqual([['_meta/brain', 'doctor', '--quick']])
  expect(status).toContain('health: 1 to look at')
  for (const surface of SURFACES) {
    const band = await $.ui.mount({ ...BAND, surface })
    expect(await band.find({ type: 'Text', text: /Health check: 1 to look at/ })).toBeDefined()
    await band.unmount()
  }
})

test('with nothing to look at the band is left to the engine', async ($, on) => {
  world(on, HEALTHY)
  await start($)
  const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await band.find({ type: 'Box', key: 'engine-band' })).toBeDefined()
  await band.unmount()
})

test('the pane lists what needs attention, and Fix it fills the prompt without sending it', async ($, on) => {
  const { filled, submitted } = world(on, DOCTOR)
  const answer = await start($)
  expect(answer.text).toBe('Health check: 1 to look at.')
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /git: 3 uncommitted changes/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /2 checks ok/ })).toBeDefined()
  await ui.press({ key: 'h-ask-fix' })
  expect(filled).toEqual(['Fix what the brain health check reports'])
  expect(submitted).toEqual([])
  await ui.unmount()
})

test('on the desktop a press posts through the kit, and a forged post does nothing', async ($, on) => {
  const { filled } = world(on, DOCTOR)
  await start($, 'desktop')
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.post({ kit: 1, act: { do: 'ask', id: 'rm -rf /' } }, { in: 'h-ask-fix' })
  await ui.post({ kit: 1, act: { do: 'shell', command: 'ls' } }, { in: 'h-ask-fix' })
  expect(filled).toEqual([])
  await ui.pointer({ type: 'down', x: 1, y: 0, button: 'left', in: 'h-ask-explain' })
  await ui.pointer({ type: 'up', x: 1, y: 0, button: 'left', in: 'h-ask-explain' })
  expect(filled).toEqual(['Explain what the brain health check reports, without changing anything'])
  await ui.unmount()
})

test('when the health check cannot run, the pane says so and nothing throws', async ($, on) => {
  world(on, '', true)
  await start($)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /could not run here/ })).toBeDefined()
  await ui.unmount()
  const answer = await $.command.run({ ...RUN, args: 'refresh' })
  expect(answer.text).toBe('The health check could not run here.')
})

test('Hide puts the band away until the next reading', async ($, on) => {
  world(on, DOCTOR)
  await start($)
  const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await band.press({ key: 'band-hide' })
  await band.unmount()
  const again = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await again.find({ type: 'Box', key: 'engine-band' })).toBeDefined()
  await again.unmount()
})

test('a value an older version stored under another shape is read as empty', async ($, on) => {
  world(on, HEALTHY, true)
  on('state.get', { key: 'findings' }, () => ({ value: { value: [{ old: 'shape' }], version: 1 } }))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /Nothing read yet/ })).toBeDefined()
  await ui.unmount()
})
