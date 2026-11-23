import { useEffect, useRef } from 'react'

const focusable = 'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
const openDialogs: HTMLElement[] = []

export function useDialogFocus(open: boolean, dismiss: () => void) {
  const panelRef = useRef<HTMLDivElement>(null)
  const dismissRef = useRef(dismiss)
  dismissRef.current = dismiss

  useEffect(() => {
    const panel = panelRef.current
    if (!open || !panel) return

    const trigger = document.activeElement
    openDialogs.push(panel)
    const controls = () => Array.from(panel.querySelectorAll<HTMLElement>(focusable))
      .filter(element => element.getClientRects().length > 0)
    const frame = requestAnimationFrame(() => {
      if (!panel.contains(document.activeElement)) (controls()[0] ?? panel).focus()
    })

    const onKey = (event: KeyboardEvent) => {
      if (openDialogs[openDialogs.length - 1] !== panel) return
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        dismissRef.current()
      }
      if (event.key !== 'Tab') return

      const items = controls()
      const at = items.findIndex(element => element === document.activeElement)
      if (at === -1 || (event.shiftKey ? at === 0 : at === items.length - 1)) {
        event.preventDefault()
        const next = (event.shiftKey ? items[items.length - 1] : items[0]) ?? panel
        next.focus()
      }
    }

    document.addEventListener('keydown', onKey, true)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('keydown', onKey, true)
      const index = openDialogs.indexOf(panel)
      const wasTop = index === openDialogs.length - 1
      if (index !== -1) openDialogs.splice(index, 1)
      if (wasTop && trigger instanceof HTMLElement && trigger.isConnected) trigger.focus()
    }
  }, [open])

  return panelRef
}
