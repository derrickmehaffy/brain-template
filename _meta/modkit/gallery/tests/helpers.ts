// What sits beneath the gallery in a test: commands, the pane, the clock and the band.
import type { On } from 'claude-code'
import { mock } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

export const NOW = Date.parse('2026-11-02T14:00:00Z')

export const PANE = {
  component: 'Pane',
  requestId: 'brain-modkit',
  props: { title: 'Mod kit', isFocused: true, bodyColumns: 64, placement: 'dock', scroll: { offset: 0, bodyRows: 80 }, view: {} },
} as const

export const BAND = {
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 90, scroll: { offset: 0, bodyRows: 6 }, view: {} },
} as const

export const SURFACES = ['terminal', 'desktop'] as const
export type Surface = (typeof SURFACES)[number]

export function world(on: On) {
  const opened: string[] = []
  mock.clock(on, { now: NOW })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('ui.open', ($, e) => { opened.push(e.id); return { value: { isPlaced: true } } })
  // What the engine draws in the band when the gallery leaves it alone.
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => $.ui.resolve(e).Box({ key: 'engine-band' }))
  return { opened }
}

export async function open($: Engine, surface: Surface, columns = 64) {
  await $.session.start({ cwd: '/w', surface, isInteractive: true })
  await $.command.run({ command: 'modkit', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } })
  return $.ui.mount({ plugin: 'brain-modkit', surface, ...PANE, props: { ...PANE.props, bodyColumns: columns } })
}

type Drawing = {
  find: (q: { key?: string; type?: string; text?: string | RegExp; in?: string }) => Promise<{ text?: string } | undefined>
  press: (t: { key: string }) => Promise<unknown>
  pointer: (e: { type: 'down' | 'up' | 'enter' | 'leave' | 'move'; x: number; y: number; button?: 'left'; in?: string }) => Promise<void>
}

// Presses a kit button on either surface: a pointer click inside its Client on the desktop, the
// host Button's press in the terminal.
export async function click(ui: Drawing, key: string, surface: Surface) {
  if (surface === 'terminal') return ui.press({ key })
  await ui.pointer({ type: 'down', x: 1, y: 0, button: 'left', in: key })
  await ui.pointer({ type: 'up', x: 1, y: 0, button: 'left', in: key })
}

// A kit button's label on either surface.
export async function label(ui: Drawing, key: string, surface: Surface): Promise<string | undefined> {
  if (surface === 'terminal') return (await ui.find({ type: 'Button', key }))?.text?.trim()
  return (await ui.find({ type: 'Text', in: key }))?.text?.trim()
}
