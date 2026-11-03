// The gallery's state contract: each value it keeps in $.state, under the plugin's name.
export type GalleryTab = 'pieces' | 'numbers' | 'layouts' | 'band'
export type BandShown = 'idle' | 'working' | 'decision'

declare module 'claude-code' {
  interface PluginState {
    'brain-modkit': {
      tab: GalleryTab
      notice: string | null
      confirming: string | null
      chip: string
      band: BandShown | null
    }
  }
}
