import { useState, useCallback, useEffect, useRef } from 'react'
import { v4 as uuidv4 } from 'uuid'
import { apiClient } from '@/api/client'
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
  createConversation: (messages?: Message[]) => string
  saveConversation: (messages: Message[], id?: string) => string
  loadConversation: (id: string) => Conversation | null
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

const SAVE_DEBOUNCE_MS = 600

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

  // (Re)load from the backend whenever the logged-in user changes.
  useEffect(() => {
    if (!userId) {
      updateConversations(() => [])
      setCurrentId(null)
      return
    }
    const controller = new AbortController()
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
        if (!saved || saved.updatedAt <= pending.updatedAt) {
          indexed.set(pending.id, pending)
        } else {
          failedSaves.current.delete(pending.id)
          pendingSaves.current.delete(pending.id)
        }
      }
      storeSaveQueue(userId, pendingSaves.current)
      setHasUnsavedChanges(failedSaves.current.size > 0)
      updateConversations(previous => {
        for (const draft of previous) {
          if (!indexed.has(draft.id) && !draft.messages.length) indexed.set(draft.id, draft)
        }
        return [...indexed.values()].sort((a, b) => b.updatedAt - a.updatedAt)
      })
    }

    setIsLoading(true)
    apiClient
      .fetchConversations(userId, controller.signal)
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
      for (const timer of saveTimers.current.values()) clearTimeout(timer)
      saveTimers.current.clear()
      pendingSaves.current.clear()
      failedSaves.current.clear()
      setHasUnsavedChanges(false)
    }
  }, [userId, updateConversations])

  const persist = useCallback((conv: Conversation, immediate = false) => {
    if (!userId || activeUser.current !== userId) return
    pendingSaves.current.set(conv.id, conv)
    storeSaveQueue(userId, pendingSaves.current)
    const pending = saveTimers.current.get(conv.id)
    if (pending) clearTimeout(pending)

    const send = () => {
      saveTimers.current.delete(conv.id)
      const previous = writes.current.get(conv.id) ?? Promise.resolve()
      const write = previous.then(async () => {
        if (activeUser.current !== userId || pendingSaves.current.get(conv.id) !== conv) return
        try {
          await apiClient.saveConversationRemote(userId, conv)
          if (activeUser.current !== userId) return
          if (pendingSaves.current.get(conv.id) === conv) {
            pendingSaves.current.delete(conv.id)
            failedSaves.current.delete(conv.id)
            storeSaveQueue(userId, pendingSaves.current)
          }
        } catch {
          if (activeUser.current !== userId) return
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
    else saveTimers.current.set(conv.id, setTimeout(send, SAVE_DEBOUNCE_MS))
  }, [userId])

  const retrySaves = useCallback(() => {
    for (const conversation of conversationsRef.current) {
      if (failedSaves.current.has(conversation.id)) persist(conversation, true)
    }
  }, [persist])

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
    updateConversations(prev => [conv, ...prev])
    setCurrentId(id)
    if (messages.length) persist(conv, true)
    return id
  }, [persist, updateConversations])

  const saveConversation = useCallback((messages: Message[], id?: string): string => {
    const now = Date.now()
    const existingId = id ?? currentId

    if (existingId) {
      const hadMessages = conversationsRef.current.some(conv => conv.id === existingId && conv.messages.length > 0)
      let updated: Conversation | undefined
      updateConversations(prev =>
        prev.map(c => {
          if (c.id !== existingId) return c
          updated = {
            ...c,
            messages,
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
    if (messages.length) persist(conv, true)
    return newId
  }, [currentId, persist, updateConversations])

  const loadConversation = useCallback((id: string): Conversation | null => {
    const conv = conversations.find(c => c.id === id) ?? null
    if (conv) setCurrentId(id)
    return conv
  }, [conversations])

  const deleteConversation = useCallback((id: string) => {
    const pending = saveTimers.current.get(id)
    if (pending) { clearTimeout(pending); saveTimers.current.delete(id) }

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
      }).catch(err => console.error('Failed to delete conversation:', err))
    }
  }, [currentId, userId, updateConversations])

  const renameConversation = useCallback((id: string, title: string, automatic = false) => {
    const trimmed = title.trim()
    if (!trimmed) return
    let updated: Conversation | undefined
    updateConversations(prev =>
      prev.map(c => {
        if (c.id !== id || (automatic && c.customTitle)) return c
        updated = { ...c, title: trimmed, customTitle: true, updatedAt: Date.now() }
        return updated
      })
    )
    if (updated) persist(updated, true)
  }, [persist, updateConversations])

  const assignToProject = useCallback((id: string, projectId: string | null) => {
    let updated: Conversation | undefined
    updateConversations(prev =>
      prev.map(c => {
        if (c.id !== id) return c
        updated = { ...c, projectId, updatedAt: Date.now() }
        return updated
      })
    )
    if (updated) persist(updated, true)
  }, [persist, updateConversations])

  const togglePin = useCallback((id: string) => {
    let updated: Conversation | undefined
    updateConversations(prev =>
      prev.map(c => {
        if (c.id !== id) return c
        updated = { ...c, pinned: !c.pinned }
        return updated
      })
    )
    if (updated) persist(updated, true)
  }, [persist, updateConversations])

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
    createConversation,
    saveConversation,
    loadConversation,
    deleteConversation,
    renameConversation,
    togglePin,
    assignToProject,
    exportAsJSON,
    exportAsMarkdown,
    setCurrentId,
  }
}
