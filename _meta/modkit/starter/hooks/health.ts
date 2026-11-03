// Where the mod's data comes from, kept apart from the drawing so it can be replaced and tested
// on its own. This one reads the brain's health check: `_meta/brain doctor --quick` prints one
// `ok`, `WARN` or `BLOCK` line per check, reads only, and skips the slow checks and the network.
//
// Replace READ and parse() to show something else: a script under ./scripts/ that prints JSON,
// a file the brain keeps (read it with $.fs.read instead), a command's output. Keep the rules:
// read-only, an argument list rather than a shell string, and a time limit.
import type { Finding, Level } from '../types'

export const READ = ['_meta/brain', 'doctor', '--quick'] as const
export const READ_TIMEOUT_MS = 60_000

const LINE = /^(ok|WARN|BLOCK)\s+([^:]+):\s*(.*)$/

export function parse(stdout: string): Finding[] {
  const found: Finding[] = []
  for (const raw of stdout.split('\n')) {
    const m = raw.trim().match(LINE)
    if (!m) continue
    const level = (m[1] ?? 'ok').toLowerCase() as Level
    found.push({ level, subject: (m[2] ?? '').trim().slice(0, 80), message: (m[3] ?? '').trim().slice(0, 300) })
  }
  return found
}

// What needs the person, worst first.
export function attention(findings: Finding[]): Finding[] {
  return findings.filter(f => f.level !== 'ok').sort((a, b) => (a.level === b.level ? 0 : a.level === 'block' ? -1 : 1))
}

export function summary(findings: Finding[]): string {
  const blocks = findings.filter(f => f.level === 'block').length
  const warns = findings.filter(f => f.level === 'warn').length
  if (!blocks && !warns) return findings.length ? `all ${findings.length} checks ok` : 'nothing read yet'
  return [blocks && `${blocks} blocking`, warns && `${warns} to look at`].filter(Boolean).join(', ')
}
