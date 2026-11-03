import { atom, read, update } from 'claude-code'
import type { EngineInterface, JsonValue, Register } from 'claude-code'

import { makeKit, onMessage } from './kit'
import type { Elements, Kit, MotionProps, PressProps } from './kit'
import { READ, READ_TIMEOUT_MS, attention, parse, summary } from './health'
import type { Finding } from '../types'

// modkit-starter: shows what this brain's health check says needs attention.
//
//   /modkit-starter          opens a pane: what needs attention, and a button that puts a
//                            request to fix it in the prompt (never sends it)
//   /modkit-starter refresh  reads the health check again; its text reply works where nothing draws
//   the band                 above the prompt, only while something needs attention
//   the status line          the same count, in a word or two
//
// It reads, and changes nothing: the one command it runs is read-only, and a button only fills
// the prompt for the person to send. It is the starting point `_meta/brain mods new` copies:
// replace hooks/health.ts to show something else, and delete any part you do not need.
//
// Drawn with the brain's mod kit (hooks/kit/, a copy kept in step by `_meta/brain mods sync`;
// never edit the copy).

const PANE = 'modkit-starter'
// Read again after a turn at most this often, so a busy session does not run it every turn.
const REREAD_MS = 5 * 60_000

// Change the shape tag when Finding's fields change: a value an older version stored is then
// read as [] rather than misread.
const findings = atom({ plugin: 'modkit-starter', key: 'findings' } as const, [], { shape: 'findings-1' })
const readAt = atom({ plugin: 'modkit-starter', key: 'readAt' } as const, null)
const failure = atom({ plugin: 'modkit-starter', key: 'failure' } as const, null)
const reading = atom({ plugin: 'modkit-starter', key: 'reading' } as const, false)
const hidden = atom({ plugin: 'modkit-starter', key: 'hidden' } as const, false)

// The requests a button may put in the prompt, by id. A press names an id, never free text, so a
// forged press cannot write whatever it likes into the prompt.
const ASKS = {
  fix: 'Fix what the brain health check reports',
  explain: 'Explain what the brain health check reports, without changing anything',
} as const
type AskId = keyof typeof ASKS

// Every act a button may carry, and the validator every press goes through.
type Act = { do: 'refresh' } | { do: 'open' } | { do: 'hide' } | { do: 'ask'; id: AskId }

function actOf(a: unknown): Act | null {
  if (!a || typeof a !== 'object') return null
  const d = a as Record<string, unknown>
  if (d['do'] === 'refresh' || d['do'] === 'open' || d['do'] === 'hide') return { do: d['do'] }
  if (d['do'] === 'ask' && typeof d['id'] === 'string' && d['id'] in ASKS) return { do: 'ask', id: d['id'] as AskId }
  return null
}

// Reads the health check. Never throws: a failure is shown, and the last good reading stays.
// A read already running is shared rather than started twice, so a burst of events costs one run.
let inFlight: Promise<void> | null = null

function refresh($: EngineInterface): Promise<void> {
  if (!inFlight) inFlight = readHealth($).finally(() => { inFlight = null })
  return inFlight
}

async function readHealth($: EngineInterface): Promise<void> {
  await update($, reading, () => true)
  try {
    const ran = await $.process.run(READ, { timeoutMs: READ_TIMEOUT_MS })
    const parsed = parse(ran.stdout)
    if (parsed.length === 0) {
      // Say what failed in words, never the raw output: it could hold anything.
      await update($, failure, () => `The health check printed nothing it could read (exit ${ran.exitCode}).`)
    } else {
      const now = await $.clock.now()
      await update($, findings, () => parsed)
      await update($, readAt, () => now)
      await update($, failure, () => null)
      await update($, hidden, () => false)
    }
  } catch {
    await update($, failure, () => 'The health check could not run here.')
  } finally {
    await update($, reading, () => false)
  }
  const left = attention(await read($, findings))
  $.ui.status(left.length ? `health: ${summary(left)}` : undefined)
}

async function perform($: EngineInterface, a: Act): Promise<void> {
  if (a.do === 'refresh') await refresh($)
  else if (a.do === 'open') await $.ui.open({ id: PANE, title: 'Health' })
  else if (a.do === 'hide') await update($, hidden, () => true)
  else await $.prompt.fill({ text: ASKS[a.id], mode: 'replace' })
}

// The kit for one drawing. The Client module paths must be string literals in this file: the
// engine reads them off its source when the mod loads. On the desktop, buttons are the kit's
// Client; elsewhere they are the host's Button and run their act through `perform`.
function kitFor($: EngineInterface, surface: string, width: number, els: Elements): Kit {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const Client = (els as any).Client
  return makeKit({
    el: els,
    surface,
    width,
    clients: Client && surface === 'desktop'
      ? {
        button: (key: string, p: PressProps) => <Client key={key} module="./kit/button.tsx" props={p} />,
        motion: (key: string, p: MotionProps) => <Client key={key} module="./kit/motion.tsx" props={p} />,
      }
      : undefined,
    perform: (act: JsonValue) => {
      const a = actOf(act)
      if (a) void perform($, a)
    },
  })
}

function clock(at: number | null): string {
  if (!at) return 'not read yet'
  const d = new Date(at)
  return `read ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function pane(k: Kit, all: Finding[], at: number | null, failed: string | null, busy: boolean) {
  const { Text } = k.env.el
  const left = attention(all)
  const ok = all.length - left.length
  return k.Overview({
    key: 'health',
    header: k.Section({ key: 'h-head', title: 'Health check', note: busy ? 'reading…' : clock(at),
      action: k.IconButton({ id: 'h-refresh', label: '↻', act: { do: 'refresh' } }) }),
    headline: all.length > 0 && k.Metrics({ key: 'h-metrics', items: [
      { value: String(left.filter(f => f.level === 'block').length), label: 'blocking', tone: 'alert' },
      { value: String(left.filter(f => f.level === 'warn').length), label: 'to look at', tone: 'you' },
      { value: String(ok), label: 'ok', tone: 'ok' },
    ] }),
    focus: failed
      ? k.Failed({ key: 'h-failed', text: failed, retry: { id: 'h-retry', label: 'Try again', act: { do: 'refresh' } } })
      : all.length === 0
        ? (busy ? k.Loading({ key: 'h-loading', label: 'Reading the health check…', lines: [70, 50] })
          : k.Empty({ key: 'h-empty', title: 'Nothing read yet', text: 'Read it now with', command: '/modkit-starter refresh' }))
        : left.length === 0
          ? k.Notice({ key: 'h-clear', tone: 'ok', text: 'Nothing needs attention.' })
          : k.List({ key: 'h-list', children: left.map((f, i) => k.Row({
            id: `h-row-${i}`, name: `${f.subject}: ${f.message}`,
            pills: [k.Pill({ key: `h-pill-${i}`, tone: f.level === 'block' ? 'alert' : 'you', text: f.level === 'block' ? 'blocking' : 'look at' })],
          })) }),
    body: left.length > 0 && k.Next({ key: 'h-next', text: 'Ask Claude to fix it', reason: 'The request goes in the prompt; nothing runs until you send it.',
      actions: [k.PromptChip({ id: 'h-ask-fix', text: 'Fix it', act: { do: 'ask', id: 'fix' } }),
        k.Button({ id: 'h-ask-explain', label: 'Explain first', look: 'quiet', act: { do: 'ask', id: 'explain' } })] }),
    folded: ok > 0 && <Text color="subtle">{`${ok} checks ok`}</Text>,
  })
}

export const register: Register = on => {
  let lastRead = 0

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'modkit-starter', description: 'What the brain health check says needs attention; add "refresh" to read it again' })
    // Read in the background: session.start is awaited before the first prompt.
    lastRead = await $.clock.now()
    void refresh($)
    return next(e)
  })

  on('command.run', { command: 'modkit-starter' }, async ($, e) => {
    if (/\brefresh\b/.test(e.args)) await refresh($)
    else {
      // A reading under way (the one session.start began) is waited for, so the reply is current.
      if (inFlight) await inFlight
      await $.ui.open({ id: PANE, title: 'Health' })
    }
    const failed = await read($, failure)
    // The reply is text, so the command is useful where nothing draws (claude -p, a phone).
    return { text: failed ?? `Health check: ${summary(await read($, findings))}.` }
  })

  on('turn.complete', async ($, e, next) => {
    try {
      const now = await $.clock.now()
      if (now - lastRead >= REREAD_MS) {
        lastRead = now
        void refresh($)
      }
    } catch {
      // the turn ends whatever happens here
    }
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const els = $.ui.resolve(e)
    const k = kitFor($, e.surface, e.props.bodyColumns || 60, els)
    return pane(k, await read($, findings), await read($, readAt), await read($, failure), await read($, reading))
  })

  // The band: only while something needs attention and the person has not hidden it. The rest of
  // the time it hands the band on with next(e), so the engine (or another mod) draws it.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const left = attention(await read($, findings))
    if (e.props.hasSurvey || left.length === 0 || (await read($, hidden))) return next(e)
    const k = kitFor($, e.surface, e.props.bodyColumns || 80, $.ui.resolve(e))
    const first = left[0]
    return k.BandDecision({
      key: 'health-band',
      question: `Health check: ${summary(left)}`,
      note: first ? `· ${first.subject}` : undefined,
      actions: [
        k.Button({ id: 'band-show', label: 'Show', look: 'primary', act: { do: 'open' } }),
        k.IconButton({ id: 'band-hide', label: '×', act: { do: 'hide' } }),
      ],
    })
  })

  // A desktop press arrives here from the kit's button Client; onMessage takes only a post from
  // that module, and only an act actOf accepts.
  on('ui.message', async ($, e, next) => {
    const handled = onMessage(e, actOf, a => void perform($, a))
    return handled ? {} : next(e)
  })
}
