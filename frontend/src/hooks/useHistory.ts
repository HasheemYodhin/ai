import { useState, useCallback, useEffect, useRef, useReducer } from 'react'
import { v4 as uuidv4 } from 'uuid'
import { apiClient, ConversationConflictError } from '@/api/client'
import type { Conversation, Message } from '@/types'

function generateTitle(messages: Message[]): string {
  const first = messages.find(m => m.role === 'user')
  if (!first) return 'New conversation'
  const text = first.content.trim()
    || first.documentAttachments?.[0]?.name
    || 'New conversation'
  const maxLen = 60
  if (text.length <= maxLen) return text
  return text.slice(0, maxLen).trimEnd() + '…'
}

function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4)
}

function countTokens(messages: Message[]): number {
  return messages.reduce((sum, m) => sum + estimateTokens(m.content), 0)
}

interface UseHistoryReturn {
  conversations: Conversation[]
  currentId: string | null
  isLoading: boolean
  hasUnsavedChanges: boolean
  retrySaves: () => void
  saveConflictCopy: (() => Promise<void>) | null
  deleteError: string | null
  createConversation: (messages?: Message[]) => string
  saveConversation: (messages: Message[], id?: string) => string
  /** Sync lookup; `messages` is [] for a chat whose messages aren't loaded yet. */
  loadConversation: (id: string) => Conversation | null
  /** Selects a chat and resolves with its full messages (fetched if needed). */
  loadConversationAsync: (id: string) => Promise<Conversation | null>
  /** Any chat by id, including the current unsent draft (not in `conversations`). */
  getConversation: (id: string | null) => Conversation | null
  deleteConversation: (id: string) => void
  renameConversation: (id: string, title: string, automatic?: boolean) => void
  togglePin: (id: string) => void
  assignToProject: (id: string, projectId: string | null) => void
  exportAsJSON: (id: string) => string | null
  exportAsMarkdown: (id: string) => string | null
  setCurrentId: (id: string | null) => void
}

function readSaveQueue(userId: string): Conversation[] {
  try {
    const pending: unknown = JSON.parse(localStorage.getItem(`dabba-pending-conversations:${userId}`) ?? '[]')
    return Array.isArray(pending) ? pending : []
  } catch {
    return []
  }
}

function storeSaveQueue(userId: string, pending: Map<string, Conversation>) {
  const key = `dabba-pending-conversations:${userId}`
  try {
    if (pending.size) localStorage.setItem(key, JSON.stringify([...pending.values()]))
    else localStorage.removeItem(key)
  } catch {
    // Keep retrying in memory when browser storage is disabled or full.
  }
}

// Trailing debounce per conversation: one PUT per burst of updates (the user
// message, streamed reply and auto-title of one turn usually land together).
const SAVE_DEBOUNCE_MS = 800

/** True when `messages` is a real (possibly empty) list, not an unloaded placeholder. */
function hasLoadedMessages(conv: Conversation): boolean {
  return conv.messagesLoaded !== false
}

/**
 * Conversations now live server-side (SQLite, scoped by userId) instead of
 * localStorage — see dabba/api/conversations_endpoints.py. Rapid saves while
 * a reply is streaming are debounced per-conversation so we don't fire a
 * network request on every token; deliberate low-frequency actions (rename,
 * pin, delete, create) persist immediately.
 */
export function useHistory(userId: string | null): UseHistoryReturn {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const conversationsRef = useRef<Conversation[]>([])
  const pendingSaves = useRef(new Map<string, Conversation>())
  const activeUser = useRef(userId)
  activeUser.current = userId
  const failedSaves = useRef(new Map<string, Conversation>())
  const [conflict, setConflict] = useState<Conversation | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const savedRevisions = useRef(new Map<string, number>())
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const updateConversations = useCallback((update: (previous: Conversation[]) => Conversation[]) => {
    const next = update(conversationsRef.current)
    conversationsRef.current = next
    setConversations(next)
  }, [])
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const writes = useRef(new Map<string, Promise<void>>())
  const saveTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  // Send functions for debounced saves that haven't fired yet, so they can be
  // flushed early (tab hidden/closing, switching chats).
  const pendingSends = useRef(new Map<string, (opts?: { keepalive?: boolean }) => void>())
  // New chats stay here until their first message, so the sidebar never shows
  // (or persists) empty "New conversation" entries that vanish on reload.
  const drafts = useRef(new Map<string, Conversation>())
  const [, bumpDrafts] = useReducer((n: number) => n + 1, 0)
  const loads = useRef(new Map<string, Promise<Conversation | null>>())

  // (Re)load from the backend whenever the logged-in user changes.
  useEffect(() => {
    if (!userId) {
      updateConversations(() => [])
      setCurrentId(null)
      return
    }
    // Each ref holds one Map for the hook's lifetime (never reassigned), so
    // capturing them here is equivalent and satisfies react-hooks lint.
    const revisions = savedRevisions.current
    const timers = saveTimers.current
    const sends = pendingSends.current
    const draftMap = drafts.current
    const loadMap = loads.current
    const saves = pendingSaves.current
    const failed = failedSaves.current
    const controller = new AbortController()
    setConflict(null)
    setDeleteError(null)
    const restored = readSaveQueue(userId)
    for (const conversation of restored) {
      pendingSaves.current.set(conversation.id, conversation)
      failedSaves.current.set(conversation.id, conversation)
    }
    setHasUnsavedChanges(restored.length > 0)

    const mergeHistory = (remote: Conversation[]) => {
      if (controller.signal.aborted) return
      const indexed = new Map(remote.map(conversation => [conversation.id, conversation]))
      for (const pending of pendingSaves.current.values()) {
        const saved = indexed.get(pending.id)
        if (saved?.revision !== undefined && saved.revision !== pending.revision) {
          setConflict(current => current ?? pending)
        }
        indexed.set(pending.id, pending)
      }
      storeSaveQueue(userId, pendingSaves.current)
      setHasUnsavedChanges(failedSaves.current.size > 0)
      updateConversations(previous => {
        // Keep messages already loaded in this session; the light list only
        // carries metadata.
        for (const local of previous) {
          const remote = indexed.get(local.id)
          if (remote && remote.messagesLoaded === false && hasLoadedMessages(local) && (remote.revision === undefined ? local.updatedAt >= remote.updatedAt : local.revision === remote.revision)) {
            indexed.set(local.id, { ...remote, messages: local.messages, messagesLoaded: true })
          }
        }
        return [...indexed.values()].sort((a, b) => b.updatedAt - a.updatedAt)
      })
    }

    // The light list has no message bodies. App restores the last open chat
    // (key below, written by App.tsx) as soon as loading ends, so fetch that
    // one chat's messages before finishing the load.
    const withRestoredChat = async (remote: Conversation[]): Promise<Conversation[]> => {
      const restoredId = localStorage.getItem(`dabba_current_conversation_id_${userId}`)
      const index = remote.findIndex(c => c.id === restoredId)
      if (index < 0 || remote[index].messagesLoaded !== false) return remote
      try {
        const full = await apiClient.fetchConversation(remote[index].id, controller.signal)
        const next = [...remote]
        next[index] = full
        return next
      } catch {
        return remote
      }
    }

    setIsLoading(true)
    apiClient
      .fetchConversations(userId, controller.signal)
      .then(withRestoredChat)
      .then(mergeHistory)
      .catch(err => {
        if (err.name !== 'AbortError') {
          mergeHistory([])
          console.error('Failed to load conversations:', err)
        }
      })
      .finally(() => { if (!controller.signal.aborted) setIsLoading(false) })
    return () => {
      controller.abort()
      for (const timer of timers.values()) clearTimeout(timer)
      timers.clear()
      sends.clear()
      draftMap.clear()
      loadMap.clear()
      revisions.clear()
      saves.clear()
      failed.clear()
      setHasUnsavedChanges(false)
    }
  }, [userId, updateConversations])

  const persist = useCallback((conv: Conversation, immediate = false) => {
    if (!userId || activeUser.current !== userId) return
    pendingSaves.current.set(conv.id, conv)
    storeSaveQueue(userId, pendingSaves.current)
    const pending = saveTimers.current.get(conv.id)
    if (pending) clearTimeout(pending)

    const send = (opts: { keepalive?: boolean } = {}) => {
      saveTimers.current.delete(conv.id)
      pendingSends.current.delete(conv.id)
      const previous = writes.current.get(conv.id) ?? Promise.resolve()
      const write = previous.then(async () => {
        if (activeUser.current !== userId || pendingSaves.current.get(conv.id) !== conv) return
        try {
          const revision = Math.max(conv.revision ?? 0, savedRevisions.current.get(conv.id) ?? 0)
          let toSave = { ...conv, revision }
          if (!hasLoadedMessages(conv)) {
            // Metadata change (rename/pin/project) on a chat never opened:
            // its `messages` is a placeholder [], and a PUT would erase the
            // real history. Fetch the stored messages and save those.
            const stored = await apiClient.fetchConversation(conv.id)
            toSave = { ...toSave, messages: stored.messages, messagesLoaded: true }
          }
          const savedRevision = await apiClient.saveConversationRemote(userId, toSave, opts)
          if (activeUser.current !== userId) return
          if (savedRevision !== undefined) savedRevisions.current.set(conv.id, savedRevision)
          if (pendingSaves.current.get(conv.id) === conv) {
            pendingSaves.current.delete(conv.id)
            failedSaves.current.delete(conv.id)
            storeSaveQueue(userId, pendingSaves.current)
          }
        } catch (error) {
          if (activeUser.current !== userId) return
          if (error instanceof ConversationConflictError) {
            setConflict(pendingSaves.current.get(conv.id) ?? conv)
            return
          }
          if (pendingSaves.current.has(conv.id)) failedSaves.current.set(conv.id, conv)
        }
        setHasUnsavedChanges(failedSaves.current.size > 0)
      })
      writes.current.set(conv.id, write)
      void write.then(() => {
        if (writes.current.get(conv.id) === write) writes.current.delete(conv.id)
      })
    }

    if (immediate) send()
    else {
      pendingSends.current.set(conv.id, send)
      saveTimers.current.set(conv.id, setTimeout(() => send(), SAVE_DEBOUNCE_MS))
    }
  }, [userId])

  /** Send debounced saves now (one chat, or all). */
  const flushSaves = useCallback((id?: string, opts?: { keepalive?: boolean }) => {
    for (const [conversationId, send] of [...pendingSends.current]) {
      if (id && conversationId !== id) continue
      const timer = saveTimers.current.get(conversationId)
      if (timer) clearTimeout(timer)
      send(opts)
    }
  }, [])

  // Don't lose the last debounced save when the tab is hidden or closed.
  // (Unsent saves are also kept in localStorage and retried on next load.)
  useEffect(() => {
    const onHide = () => { if (document.visibilityState === 'hidden') flushSaves(undefined, { keepalive: true }) }
    const onPageHide = () => flushSaves(undefined, { keepalive: true })
    document.addEventListener('visibilitychange', onHide)
    window.addEventListener('pagehide', onPageHide)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
      window.removeEventListener('pagehide', onPageHide)
    }
  }, [flushSaves])

  const retrySaves = useCallback(() => {
    for (const conversation of conversationsRef.current) {
      if (conversation.id !== conflict?.id && failedSaves.current.has(conversation.id)) persist(conversation, true)
    }
  }, [persist, conflict])

  useEffect(() => {
    if (!hasUnsavedChanges) return
    const timer = setInterval(retrySaves, 15_000)
    window.addEventListener('online', retrySaves)
    return () => {
      clearInterval(timer)
      window.removeEventListener('online', retrySaves)
    }
  }, [hasUnsavedChanges, retrySaves])

  const createConversation = useCallback((messages: Message[] = []): string => {
    const id = uuidv4()
    const now = Date.now()
    const conv: Conversation = {
      id,
      title: generateTitle(messages),
      messages,
      createdAt: now,
      updatedAt: now,
      tokenCount: countTokens(messages),
    }
    setCurrentId(id)
    if (messages.length) {
      updateConversations(prev => [conv, ...prev])
      persist(conv, true)
    } else {
      // Only the latest empty chat is kept; older untouched drafts are dropped.
      drafts.current.clear()
      drafts.current.set(id, conv)
      bumpDrafts()
    }
    return id
  }, [persist, updateConversations])

  const saveConversation = useCallback((messages: Message[], id?: string): string => {
    const now = Date.now()
    const existingId = id ?? currentId

    if (existingId) {
      const draft = drafts.current.get(existingId)
      if (draft) {
        if (!messages.length) return existingId
        // First message: the draft becomes a real, saved conversation.
        drafts.current.delete(existingId)
        bumpDrafts()
        const promoted: Conversation = {
          ...draft,
          messages,
          title: draft.customTitle ? draft.title : generateTitle(messages),
          updatedAt: now,
          tokenCount: countTokens(messages),
        }
        updateConversations(prev => [promoted, ...prev])
        persist(promoted)
        return existingId
      }
      const target = conversationsRef.current.find(conv => conv.id === existingId)
      if (target && !hasLoadedMessages(target)) {
        // The chat view was never given this chat's real messages, so saving
        // would overwrite stored history. Callers must use loadConversationAsync.
        console.warn('Skipped saving a conversation whose messages were not loaded:', existingId)
        return existingId
      }
      const hadMessages = (target?.messages.length ?? 0) > 0
      let updated: Conversation | undefined
      updateConversations(prev =>
        prev.map(c => {
          if (c.id !== existingId) return c
          updated = {
            ...c,
            messages,
            messagesLoaded: true,
            messageCount: messages.length,
            title: c.customTitle ? c.title : generateTitle(messages),
            updatedAt: now,
            tokenCount: countTokens(messages),
          }
          return updated
        })
      )
      if (updated && (updated.messages.length || hadMessages)) persist(updated)
      return existingId
    }

    if (!messages.length) return createConversation()
    const newId = uuidv4()
    const conv: Conversation = {
      id: newId,
      title: generateTitle(messages),
      messages,
      createdAt: now,
      updatedAt: now,
      tokenCount: countTokens(messages),
    }
    updateConversations(prev => [conv, ...prev])
    setCurrentId(newId)
    persist(conv, true)
    return newId
  }, [createConversation, currentId, persist, updateConversations])

  const getConversation = useCallback((id: string | null): Conversation | null => {
    if (!id) return null
    return drafts.current.get(id) ?? conversationsRef.current.find(c => c.id === id) ?? null
  }, [])

  const loadConversation = useCallback((id: string): Conversation | null => {
    const conv = getConversation(id)
    if (conv) setCurrentId(id)
    return conv
  }, [getConversation])

  const loadConversationAsync = useCallback(async (id: string): Promise<Conversation | null> => {
    const conv = getConversation(id)
    if (!conv) return null
    // Send the chat we're leaving now rather than after the debounce.
    if (currentId && currentId !== id) flushSaves(currentId)
    setCurrentId(id)
    if (hasLoadedMessages(conv)) return conv

    // Share one request if the chat is opened twice quickly.
    let load = loads.current.get(id)
    if (!load) {
      load = apiClient.fetchConversation(id).then(full => {
        let merged: Conversation | null = null
        updateConversations(prev => prev.map(c => {
          if (c.id !== id) return c
          // Local metadata (e.g. a rename made before opening) wins.
          merged = { ...c, messages: full.messages, messagesLoaded: true, messageCount: full.messages.length }
          return merged
        }))
        return merged
      }).catch(err => {
        console.error('Failed to load conversation:', err)
        return null
      }).finally(() => { loads.current.delete(id) })
      loads.current.set(id, load)
    }
    return load
  }, [currentId, flushSaves, getConversation, updateConversations])

  const saveConflictCopy = conflict ? async () => {
    if (!userId) return
    const pending = pendingSaves.current.get(conflict.id) ?? conflict
    const stored = await apiClient.fetchConversation(conflict.id).catch(() => null)
    if (activeUser.current !== userId) return
    if (!hasLoadedMessages(pending) && !stored) {
      setDeleteError('Could not load the original messages. Your pending edit is still saved on this device.')
      return
    }
    const copy: Conversation = {
      ...pending,
      id: uuidv4(),
      revision: 0,
      title: `${pending.title} (recovered copy)`,
      messages: hasLoadedMessages(pending) ? pending.messages : stored!.messages,
      messagesLoaded: true,
      updatedAt: Date.now(),
    }
    pendingSaves.current.delete(conflict.id)
    failedSaves.current.delete(conflict.id)
    setConflict(null)
    setDeleteError(null)
    updateConversations(previous => [copy, ...previous.flatMap(item =>
      item.id === conflict.id ? (stored ? [stored] : []) : [item]
    )])
    if (currentId === conflict.id) setCurrentId(null)
    persist(copy, true)
  } : null

  const deleteConversation = useCallback((id: string) => {
    const removed = conversationsRef.current.find(item => item.id === id)
    if (conflict?.id === id) setConflict(null)
    const unsaved = pendingSaves.current.get(id)
    setDeleteError(null)
    const pending = saveTimers.current.get(id)
    if (pending) { clearTimeout(pending); saveTimers.current.delete(id) }

    pendingSends.current.delete(id)
    if (drafts.current.delete(id)) bumpDrafts()
    updateConversations(prev => prev.filter(c => c.id !== id))
    if (currentId === id) {
      setCurrentId(null)
    }
    if (userId) {
      pendingSaves.current.delete(id)
      storeSaveQueue(userId, pendingSaves.current)
      const previous = writes.current.get(id) ?? Promise.resolve()
      void previous.then(() => {
        if (activeUser.current !== userId) return
        failedSaves.current.delete(id)
        setHasUnsavedChanges(failedSaves.current.size > 0)
        return apiClient.deleteConversationRemote(userId, id)
      }).catch(() => {
        if (activeUser.current !== userId) return
        if (removed) updateConversations(previous => previous.some(item => item.id === id) ? previous : [removed, ...previous])
        if (unsaved) persist(unsaved)
        setDeleteError('Could not delete the conversation. It was restored to the sidebar.')
      })
    }
  }, [currentId, userId, updateConversations, persist, conflict])

  /** Apply a metadata change to an unsent draft. Returns true if `id` was a draft. */
  const updateDraft = useCallback((id: string, change: (draft: Conversation) => Conversation): boolean => {
    const draft = drafts.current.get(id)
    if (!draft) return false
    drafts.current.set(id, change(draft))
    bumpDrafts()
    return true
  }, [])

  const renameConversation = useCallback((id: string, title: string, automatic = false) => {
    const trimmed = title.trim()
    if (!trimmed) return
    if (updateDraft(id, d => (automatic && d.customTitle) ? d : { ...d, title: trimmed, customTitle: true })) return
    let updated: Conversation | undefined
    updateConversations(prev =>
      prev.map(c => {
        if (c.id !== id || (automatic && c.customTitle)) return c
        updated = { ...c, title: trimmed, customTitle: true, updatedAt: Date.now() }
        return updated
      })
    )
    // Auto-titles arrive right after a reply, so fold them into that debounced
    // save instead of sending a separate PUT; manual renames save at once.
    if (updated) persist(updated, !automatic)
  }, [persist, updateConversations, updateDraft])

  const assignToProject = useCallback((id: string, projectId: string | null) => {
    if (updateDraft(id, d => ({ ...d, projectId }))) return
    let updated: Conversation | undefined
    updateConversations(prev =>
      prev.map(c => {
        if (c.id !== id) return c
        updated = { ...c, projectId, updatedAt: Date.now() }
        return updated
      })
    )
    if (updated) persist(updated, true)
  }, [persist, updateConversations, updateDraft])

  const togglePin = useCallback((id: string) => {
    if (updateDraft(id, d => ({ ...d, pinned: !d.pinned }))) return
    let updated: Conversation | undefined
    updateConversations(prev =>
      prev.map(c => {
        if (c.id !== id) return c
        updated = { ...c, pinned: !c.pinned }
        return updated
      })
    )
    if (updated) persist(updated, true)
  }, [persist, updateConversations, updateDraft])

  const exportAsJSON = useCallback((id: string): string | null => {
    const conv = conversations.find(c => c.id === id)
    if (!conv) return null
    return JSON.stringify(conv, null, 2)
  }, [conversations])

  const exportAsMarkdown = useCallback((id: string): string | null => {
    const conv = conversations.find(c => c.id === id)
    if (!conv) return null

    const lines: string[] = [
      `# ${conv.title}`,
      '',
      `*Exported on ${new Date(conv.createdAt).toLocaleString()}*`,
      '',
      '---',
      '',
    ]

    for (const msg of conv.messages) {
      const prefix = msg.role === 'user' ? '**You**' : '**Assistant**'
      lines.push(`${prefix}:`)
      lines.push('')
      lines.push(msg.content)
      lines.push('')
      lines.push('---')
      lines.push('')
    }

    return lines.join('\n')
  }, [conversations])

  return {
    conversations,
    currentId,
    isLoading,
    hasUnsavedChanges,
    retrySaves,
    saveConflictCopy,
    deleteError,
    createConversation,
    saveConversation,
    loadConversation,
    loadConversationAsync,
    getConversation,
    deleteConversation,
    renameConversation,
    togglePin,
    assignToProject,
    exportAsJSON,
    exportAsMarkdown,
    setCurrentId,
  }
}
