// The mod's state contract: every value it keeps in $.state, under the mod's name. A value
// declared Shaped<T> carries a tag (`shape` in register.tsx): change the tag when the value's
// fields change, so what an older version stored is read as the initial value, not misread.
export type Level = 'ok' | 'warn' | 'block'
export type Finding = { level: Level; subject: string; message: string }

declare module 'claude-code' {
  interface PluginState {
    'modkit-starter': {
      findings: Shaped<Finding[]>
      readAt: number | null
      failure: string | null
      reading: boolean
      hidden: boolean
    }
  }
}
