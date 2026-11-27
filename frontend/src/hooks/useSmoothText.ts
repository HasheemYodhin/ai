import { useEffect, useRef, useState } from 'react'

const UPDATE_INTERVAL_MS = 40
const MAX_ANIMATED_BACKLOG = 600
const TAIL_CHARS = 200

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

    let lastUpdate = 0
    const tick = (now: number) => {
      const target = targetRef.current
      const current = shownRef.current
      if (current.length >= target.length) {
        frameRef.current = 0
        return
      }
      // Each update re-parses the whole reply as markdown, so cap the update rate
      // and show large bursts (a long code block) almost at once.
      if (now - lastUpdate >= UPDATE_INTERVAL_MS) {
        lastUpdate = now
        const backlog = target.length - current.length
        const end = backlog > MAX_ANIMATED_BACKLOG
          ? target.length - TAIL_CHARS
          : current.length + Math.max(3, Math.ceil(backlog / 6))
        const next = target.slice(0, end)
        shownRef.current = next
        setShown(next)
      }
      frameRef.current = requestAnimationFrame(tick)
    }
    frameRef.current = requestAnimationFrame(tick)
  }, [text, active])

  useEffect(() => () => cancelAnimationFrame(frameRef.current), [])

  if (!everActive.current) return { text, revealing: false }
  return { text: shown, revealing: shown.length < text.length }
}
