// The mod kit. makeKit(env) binds every piece and layout to one drawing: a mod calls it once in
// each ui.render hook and draws with what it returns, `k.Card({ ... })`.
//
// This folder is copied, whole, into each mod that uses it (`hooks/kit/`), because a mod may
// only import files from inside its own folder. Never edit a copy: the kit's home is
// _meta/modkit/gallery/hooks/kit/ in the template, and `_meta/brain mods sync` refreshes copies.
import type { KitEnv } from './types'
import * as content from './content'
import * as controls from './controls'
import * as lists from './lists'
import * as dashboard from './dashboard'
import * as live from './live'
import * as chartpieces from './chartpieces'
import * as layouts from './layouts'

export type { KitEnv, Tone, Look, ButtonSpec, PressProps, MotionProps, Clients, El, Elements } from './types'
export type { RowProps } from './lists'
export type { Zone } from './layouts'
export { onMessage } from './message'
export { GLYPH, TONE_TEXT, INK, pct } from './tokens'
export { ring, stepRail, esc } from './charts'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const bind = <P,>(env: KitEnv, f: (env: KitEnv, p: P) => any) => (p: P) => f(env, p)

export function makeKit(env: KitEnv) {
  return {
    env,
    // controls
    Button: bind(env, controls.Button),
    IconButton: bind(env, controls.IconButton),
    Tabs: bind(env, controls.Tabs),
    Chips: bind(env, controls.Chips),
    PromptChip: bind(env, controls.PromptChip),
    Confirm: bind(env, controls.Confirm),
    Fold: bind(env, controls.Fold),
    Field: bind(env, controls.Field),
    Picker: bind(env, controls.Picker),
    // content
    Section: bind(env, content.Section),
    Card: bind(env, content.Card),
    Pill: bind(env, content.Pill),
    Notice: bind(env, content.Notice),
    KeyValue: bind(env, content.KeyValue),
    Banner: bind(env, content.Banner),
    Next: bind(env, content.Next),
    Decision: bind(env, content.Decision),
    Empty: bind(env, content.Empty),
    Loading: bind(env, content.Loading),
    Failed: bind(env, content.Failed),
    Timeline: bind(env, content.Timeline),
    Checklist: bind(env, content.Checklist),
    Link: bind(env, content.Link),
    Prose: bind(env, content.Prose),
    // lists
    Row: bind(env, lists.Row),
    List: bind(env, lists.List),
    Table: bind(env, lists.Table),
    // numbers
    StatTile: bind(env, dashboard.StatTile),
    Stats: bind(env, dashboard.Stats),
    Metrics: bind(env, dashboard.Metrics),
    Meter: bind(env, dashboard.Meter),
    Distribution: bind(env, dashboard.Distribution),
    Sparkline: bind(env, dashboard.Sparkline),
    // live
    Live: bind(env, live.Live),
    Countdown: bind(env, live.Countdown),
    Ticker: bind(env, live.Ticker),
    StepBar: bind(env, live.StepBar),
    // charts
    StepRail: bind(env, chartpieces.StepRail),
    Ring: bind(env, chartpieces.Ring),
    // layouts
    Overview: bind(env, layouts.Overview),
    Queue: bind(env, layouts.Queue),
    Detail: bind(env, layouts.Detail),
    DecisionLayout: bind(env, layouts.DecisionLayout),
    States: bind(env, layouts.States),
    BandIdle: bind(env, layouts.BandIdle),
    BandWorking: bind(env, layouts.BandWorking),
    BandDecision: bind(env, layouts.BandDecision),
  }
}

export type Kit = ReturnType<typeof makeKit>
