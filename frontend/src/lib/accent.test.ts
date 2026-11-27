// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import {
  ACCENT_PRESETS, ACCENT_STORAGE_KEY, DEFAULT_ACCENT, accentVars, applyAccent, contrastRatio, luminance, normalizeAccent, parseHex,
} from './accent'

const WHITE = 1
const BLACK = 0
const rgb = (hex: string) => parseHex(hex) as [number, number, number]

afterEach(() => {
  document.documentElement.removeAttribute('style')
  localStorage.clear()
})

describe('normalizeAccent', () => {
  it('keeps the default orange exactly as it is', () => {
    expect(normalizeAccent(DEFAULT_ACCENT)).toBe(DEFAULT_ACCENT)
  })

  it('falls back to the default for anything that is not a color', () => {
    expect(normalizeAccent('')).toBe(DEFAULT_ACCENT)
    expect(normalizeAccent('not a color')).toBe(DEFAULT_ACCENT)
    expect(normalizeAccent('#12345')).toBe(DEFAULT_ACCENT)
  })

  it('reads short hex colors', () => {
    expect(parseHex('#f80')).toEqual([255, 136, 0])
  })

  it.each(['#ffffff', '#ffff00', '#ffee00', '#f5f5dc', '#000000', '#050505'])(
    'makes %s readable: white text on it, and the color itself on black',
    input => {
      const value = luminance(rgb(normalizeAccent(input)))
      expect(contrastRatio(WHITE, value)).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(BLACK, value)).toBeGreaterThanOrEqual(3)
    },
  )

  it('keeps every preset readable and distinct', () => {
    for (const preset of ACCENT_PRESETS) {
      const value = luminance(rgb(preset.hex))
      expect(contrastRatio(WHITE, value), preset.name).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(BLACK, value), preset.name).toBeGreaterThanOrEqual(3)
    }
    expect(new Set(ACCENT_PRESETS.map(preset => preset.hex)).size).toBe(ACCENT_PRESETS.length)
    expect(ACCENT_PRESETS[0].hex).toBe(DEFAULT_ACCENT)
  })
})

describe('accent CSS variables', () => {
  it('produces space separated RGB triplets, which is what Tailwind needs to add opacity', () => {
    for (const value of Object.values(accentVars('#2563eb'))) expect(value).toMatch(/^\d{1,3} \d{1,3} \d{1,3}$/)
    expect(Object.keys(accentVars('#2563eb')).sort()).toEqual([
      '--accent-dark-hover-rgb', '--accent-hover-rgb', '--accent-light-rgb', '--accent-rgb',
    ])
  })

  it('sets the variables and remembers them for the next page load', () => {
    applyAccent('#7c3aed')
    expect(document.documentElement.style.getPropertyValue('--accent-rgb')).not.toBe('')
    expect(JSON.parse(localStorage.getItem(ACCENT_STORAGE_KEY) ?? '{}')['--accent-rgb']).toBe(
      document.documentElement.style.getPropertyValue('--accent-rgb'),
    )
  })

  it('removes the overrides when the default color is chosen again', () => {
    applyAccent('#7c3aed')
    applyAccent(DEFAULT_ACCENT)
    expect(document.documentElement.style.getPropertyValue('--accent-rgb')).toBe('')
    expect(localStorage.getItem(ACCENT_STORAGE_KEY)).toBeNull()
  })
})
