import { useEffect, useRef, useState } from 'react'

/**
 * Reveals streamed text a few characters per frame instead of in network-sized
 * bursts. The step grows with the backlog, so a fast model never falls behind,
 * and the reveal finishes even if the stream ends first. Text that was never
 * streamed (history) is shown at once.
 */
export function useSmoothText(text: string, active: boolean): { text: string; revealing: boolean } {
  const everActive = useRef(active)
  if (active) everActive.current = true

  const [shown, setShown] = useState(active ? '' : text)
  const shownRef = useRef(shown)
  const targetRef = useRef(text)
  const frameRef = useRef(0)
  targetRef.current = text

  useEffect(() => {
    if (!everActive.current) return
    if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      shownRef.current = text
      setShown(text)
      return
    }
    // A regenerate or edit replaces the text rather than extending it.
    if (!text.startsWith(shownRef.current)) {
      shownRef.current = ''
      setShown('')
    }
    if (frameRef.current || shownRef.current.length >= text.length) return

    const tick = () => {
      const target = targetRef.current
      const current = shownRef.current
      if (current.length >= target.length) {
        frameRef.current = 0
        return
      }
      const backlog = target.length - current.length
      const next = target.slice(0, current.length + Math.max(2, Math.ceil(backlog / 12)))
      shownRef.current = next
      setShown(next)
      frameRef.current = requestAnimationFrame(tick)
    }
    frameRef.current = requestAnimationFrame(tick)
  }, [text, active])

  useEffect(() => () => cancelAnimationFrame(frameRef.current), [])

  if (!everActive.current) return { text, revealing: false }
  return { text: shown, revealing: shown.length < text.length }
}
