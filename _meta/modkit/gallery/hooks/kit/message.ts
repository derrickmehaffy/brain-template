// onMessage: the one way a kit button reaches the mod. A desktop press posts `{ kit: 1, act }`
// from the kit's button module; this takes only a post from that module, and only an act the
// mod's own validator accepts. Anything else is answered as handled and does nothing, so a
// forged or stale post can never run an act the mod did not define.
export function onMessage<T>(
  e: { module: string; data: unknown },
  validate: (act: unknown) => T | null,
  perform: (act: T) => void,
): boolean {
  if (!/(^|\/)kit\/button\.tsx$/.test(e.module)) return false
  const d = e.data as { kit?: unknown; act?: unknown } | null
  if (!d || typeof d !== 'object' || d.kit !== 1 || d.act === undefined) return true
  const act = validate(d.act)
  if (act !== null) perform(act)
  return true
}
