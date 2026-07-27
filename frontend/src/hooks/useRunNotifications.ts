import { useCallback, useEffect, useRef, useState } from 'react'
import type { CoworkItem } from '@/types'
import { apiClient } from '@/api/client'
import { useSettings } from '@/hooks/useSettings'

export interface RunNotice {
  id: string
  tone: 'success' | 'error' | 'info'
  message: string
}

/** Prompt for OS notification permission if it hasn't been decided yet. Safe to call anywhere. */
export function requestNotificationPermission(): void {
  if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
    void Notification.requestPermission()
  }
}

// Where an item lands once its Cowork run ends, and how to phrase it.
const OUTCOME: Record<string, { tone: RunNotice['tone']; verb: string }> = {
  done: { tone: 'success', verb: 'finished' },
  blocked: { tone: 'error', verb: 'stopped and needs attention' },
  planned: { tone: 'info', verb: 'was interrupted' },
}

/**
 * Board-wide Cowork run notifications, driven off item-status transitions
 * (which CoworkPage already polls for every item). When an item leaves the
 * `in_progress` state — i.e. its run just ended — this surfaces it two ways:
 * an OS-level browser notification (fires even when the tab is backgrounded,
 * if permission was granted) and an in-app banner returned as `notices`.
 *
 * A ref remembers each item's last-seen status so a completion fires once,
 * and the first poll is skipped so pre-existing finished items stay quiet.
 */
export function useRunNotifications(items: CoworkItem[]) {
  const { settings } = useSettings()
  const seenStatus = useRef<Map<string, string>>(new Map())
  const primed = useRef(false)
  const [notices, setNotices] = useState<RunNotice[]>([])

  const requestPermission = useCallback(() => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      void Notification.requestPermission()
    }
  }, [])

  const dismiss = useCallback((id: string) => {
    setNotices(prev => prev.filter(n => n.id !== id))
  }, [])

  useEffect(() => {
    const transitions: RunNotice[] = []

    for (const item of items) {
      const prev = seenStatus.current.get(item.id)
      seenStatus.current.set(item.id, item.status)
      if (!primed.current) continue
      // Only a genuine move OUT of in_progress into a run-outcome state counts.
      if (prev !== 'in_progress' || item.status === 'in_progress') continue
      const outcome = OUTCOME[item.status]
      if (!outcome) continue

      const notice: RunNotice = {
        id: `${item.id}-${item.updatedAt}`,
        tone: outcome.tone,
        message: `“${item.title}” ${outcome.verb}`,
      }
      transitions.push(notice)

      if (settings.desktopNotifications && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        try {
          new Notification('Dabba Cowork', { body: notice.message, tag: item.id })
        } catch { /* Notification construction can throw on some platforms; ignore */ }
      }
    }

    if (transitions.length) setNotices(prev => [...transitions, ...prev].slice(0, 4))
    primed.current = true
  }, [items, settings.desktopNotifications])

  return { notices, dismiss, requestPermission }
}

const PROCESS_TERMINAL = new Set(['exited', 'failed'])

/**
 * Generalizes the same notification pattern to ANY background process
 * started via the process_start tool in a normal chat turn (e.g. a dev
 * server or long build) — not just Cowork runs. Polls GET /v1/agent/processes
 * and fires an OS notification + in-app banner the moment a process this
 * hook has already seen running transitions to exited/failed.
 *
 * Mount this once near the app root so it's active for every conversation,
 * independent of which page/tab is open.
 */
export function useProcessNotifications(pollIntervalMs = 4000) {
  const { settings } = useSettings()
  const seenStatus = useRef<Map<string, string>>(new Map())
  const [notices, setNotices] = useState<RunNotice[]>([])

  const dismiss = useCallback((id: string) => {
    setNotices(prev => prev.filter(n => n.id !== id))
  }, [])

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      let processes: Array<{ process_id: string; command: string; status: string }> = []
      try { processes = await apiClient.listBackgroundProcesses() }
      catch { return } // best-effort; a transient network error shouldn't spam anything
      if (cancelled) return

      const transitions: RunNotice[] = []
      for (const proc of processes) {
        const prev = seenStatus.current.get(proc.process_id)
        seenStatus.current.set(proc.process_id, proc.status)
        if (prev !== 'running' || !PROCESS_TERMINAL.has(proc.status)) continue

        const label = proc.command.length > 60 ? `${proc.command.slice(0, 57)}…` : proc.command
        const notice: RunNotice = {
          id: `${proc.process_id}-${proc.status}`,
          tone: proc.status === 'exited' ? 'success' : 'error',
          message: `Background process “${label}” ${proc.status === 'exited' ? 'finished' : 'failed'}`,
        }
        transitions.push(notice)
        if (settings.desktopNotifications && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
          try { new Notification('Dabba', { body: notice.message, tag: proc.process_id }) }
          catch { /* ignore */ }
        }
      }
      if (transitions.length) setNotices(prev => [...transitions, ...prev].slice(0, 4))
    }

    const timer = window.setInterval(poll, pollIntervalMs)
    void poll()
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [pollIntervalMs, settings.desktopNotifications])

  return { notices, dismiss }
}
