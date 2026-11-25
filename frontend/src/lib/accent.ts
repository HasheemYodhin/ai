/**
 * The app's accent color (buttons, links, highlights). It is a user setting:
 * Tailwind's `accent` colors read the CSS variables set here, so changing the
 * variables recolors every screen at once.
 *
 * Whatever color someone picks, white text on a button must stay readable, so
 * `normalizeAccent` darkens very light colors until white text reaches the WCAG
 * AA ratio (4.5:1), and lightens near-black ones so they still show up on the
 * dark theme (3:1 against black).
 */

export const DEFAULT_ACCENT = '#cf4419'

/** White text on the accent keeps a contrast ratio of at least 4.5:1 at or below this luminance. */
const MAX_LUMINANCE = 0.18
/** The accent keeps at least 3:1 against black at or above this luminance. */
const MIN_LUMINANCE = 0.1

export type Rgb = [number, number, number]

export function parseHex(input: string): Rgb | null {
  const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(input.trim())
  if (!match) return null
  const digits = match[1].length === 3 ? match[1].split('').map(char => char + char).join('') : match[1]
  return [0, 2, 4].map(index => parseInt(digits.slice(index, index + 2), 16)) as Rgb
}

export function toHex([r, g, b]: Rgb): string {
  return `#${[r, g, b].map(value => Math.round(value).toString(16).padStart(2, '0')).join('')}`
}

/** WCAG relative luminance, 0 (black) to 1 (white). */
export function luminance([r, g, b]: Rgb): number {
  const linear = (value: number) => {
    const channel = value / 255
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
}

export function contrastRatio(a: number, b: number): number {
  const [light, dark] = a > b ? [a, b] : [b, a]
  return (light + 0.05) / (dark + 0.05)
}

function rgbToHsl([r, g, b]: Rgb): [number, number, number] {
  const [rn, gn, bn] = [r / 255, g / 255, b / 255]
  const max = Math.max(rn, gn, bn)
  const min = Math.min(rn, gn, bn)
  const lightness = (max + min) / 2
  if (max === min) return [0, 0, lightness]
  const delta = max - min
  const saturation = lightness > 0.5 ? delta / (2 - max - min) : delta / (max + min)
  let hue: number
  if (max === rn) hue = (gn - bn) / delta + (gn < bn ? 6 : 0)
  else if (max === gn) hue = (bn - rn) / delta + 2
  else hue = (rn - gn) / delta + 4
  return [hue / 6, saturation, lightness]
}

function hslToRgb(h: number, s: number, l: number): Rgb {
  if (s === 0) return [l * 255, l * 255, l * 255]
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  const channel = (offset: number) => {
    let t = offset
    if (t < 0) t += 1
    if (t > 1) t -= 1
    if (t < 1 / 6) return p + (q - p) * 6 * t
    if (t < 1 / 2) return q
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6
    return p
  }
  return [channel(h + 1 / 3) * 255, channel(h) * 255, channel(h - 1 / 3) * 255]
}

/** Returns the color as `#rrggbb`, adjusted (hue kept) so it is readable in both themes. Invalid input gives the default. */
export function normalizeAccent(input: string): string {
  const parsed = parseHex(input)
  if (!parsed) return DEFAULT_ACCENT
  const [hue, saturation, start] = rgbToHsl(parsed)
  let lightness = start
  let rgb = parsed
  for (let step = 0; step < 400; step += 1) {
    const value = luminance(rgb)
    if (value > MAX_LUMINANCE) lightness -= 0.005
    else if (value < MIN_LUMINANCE) lightness += 0.005
    else break
    lightness = Math.min(1, Math.max(0, lightness))
    rgb = hslToRgb(hue, saturation, lightness)
  }
  return toHex(rgb)
}

const asTriplet = ([r, g, b]: Rgb) => `${Math.round(r)} ${Math.round(g)} ${Math.round(b)}`

/** The CSS variables behind Tailwind's accent, hover, tint and dark-surface text colors. */
export function accentVars(input: string): Record<string, string> {
  const base = parseHex(normalizeAccent(input)) as Rgb
  const [hue, saturation, lightness] = rgbToHsl(base)
  const hover = hslToRgb(hue, saturation, Math.max(0, lightness - 0.07))
  // A soft tint for backgrounds: 12% of the color over white.
  const tint = base.map(value => 255 - (255 - value) * 0.12) as Rgb
  // A lighter shade for text on dark surfaces.
  let raised = lightness
  let onDark = base
  for (let step = 0; step < 200 && luminance(onDark) < 0.3; step += 1) {
    raised = Math.min(1, raised + 0.01)
    onDark = hslToRgb(hue, saturation, raised)
  }
  return {
    '--accent-rgb': asTriplet(base),
    '--accent-hover-rgb': asTriplet(hover),
    '--accent-light-rgb': asTriplet(tint),
    '--accent-dark-hover-rgb': asTriplet(onDark),
  }
}

/** Remembered so the page can be colored before the app loads (see index.html). */
export const ACCENT_STORAGE_KEY = 'dabba-accent'

/** Applies the accent to the whole page. The default color needs no overrides, so they are removed. */
export function applyAccent(input: string): void {
  const root = document.documentElement
  const color = normalizeAccent(input)
  const vars = accentVars(color)
  if (color === DEFAULT_ACCENT) {
    for (const name of Object.keys(vars)) root.style.removeProperty(name)
    try { localStorage.removeItem(ACCENT_STORAGE_KEY) } catch { /* storage unavailable */ }
    return
  }
  for (const [name, value] of Object.entries(vars)) root.style.setProperty(name, value)
  try { localStorage.setItem(ACCENT_STORAGE_KEY, JSON.stringify(vars)) } catch { /* storage unavailable */ }
}

/** The current accent as a CSS color, for canvas drawing. */
export function currentAccentColor(): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue('--accent-rgb').trim()
  return value ? `rgb(${value})` : DEFAULT_ACCENT
}

export interface AccentPreset {
  id: string
  name: string
  hex: string
}

const RAW_PRESETS = [
  { id: 'orange', name: 'Orange', hex: DEFAULT_ACCENT },
  { id: 'green', name: 'Green', hex: '#1f8a4c' },
  { id: 'teal', name: 'Teal', hex: '#0f7c8a' },
  { id: 'blue', name: 'Blue', hex: '#2563eb' },
  { id: 'purple', name: 'Purple', hex: '#7c3aed' },
  { id: 'pink', name: 'Pink', hex: '#be185d' },
  { id: 'red', name: 'Red', hex: '#c62828' },
  { id: 'graphite', name: 'Graphite', hex: '#475569' },
]

/** The swatches offered in Settings, already adjusted so each one is readable. */
export const ACCENT_PRESETS: AccentPreset[] = RAW_PRESETS.map(preset => ({ ...preset, hex: normalizeAccent(preset.hex) }))
