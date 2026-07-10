import { useState, useCallback, useEffect, useRef } from 'react'
import { v4 as uuidv4 } from 'uuid'
import { apiClient } from '@/api/client'
import type { Conversation, Message } from '@/types'

function generateTitle(messages: Message[]): string {
  const first = messages.find(m => m.role === 'user')
  if (!first) return 'New conversation'
  const text = first.content.trim()
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
  createConversation: (messages?: Message[]) => string
  saveConversation: (messages: Message[], id?: string) => string
  loadConversation: (id: string) => Conversation | null
  deleteConversation: (id: string) => void
  renameConversation: (id: string, title: string) => void
  togglePin: (id: string) => void
  assignToProject: (id: string, projectId: string | null) => void
  exportAsJSON: (id: string) => string | null
  exportAsMarkdown: (id: string) => string | null
  setCurrentId: (id: string | null) => void
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
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const saveTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  // (Re)load from the backend whenever the logged-in user changes.
  useEffect(() => {
    if (!userId) {
      setConversations([])
      setCurrentId(null)
      return
    }
    const controller = new AbortController()
    setIsLoading(true)
    apiClient
      .fetchConversations(userId, controller.signal)
      .then(setConversations)
      .catch(err => {
        if (err.name !== 'AbortError') console.error('Failed to load conversations:', err)
      })
      .finally(() => setIsLoading(false))
    return () => controller.abort()
  }, [userId])

  const persist = useCallback((conv: Conversation, immediate = false) => {
    if (!userId) return
    const pending = saveTimers.current.get(conv.id)
    if (pending) clearTimeout(pending)

    const send = () => {
      saveTimers.current.delete(conv.id)
      apiClient.saveConversationRemote(userId, conv).catch(err => console.error('Failed to save conversation:', err))
    }

    if (immediate) {
      send()
    } else {
      saveTimers.current.set(conv.id, setTimeout(send, SAVE_DEBOUNCE_MS))
    }
  }, [userId])

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
    setConversations(prev => [conv, ...prev])
    setCurrentId(id)
    persist(conv, true)
    return id
  }, [persist])

  const saveConversation = useCallback((messages: Message[], id?: string): string => {
    const now = Date.now()
    const existingId = id ?? currentId

    if (existingId) {
      let updated: Conversation | undefined
      setConversations(prev =>
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
      if (updated) persist(updated)
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
    setConversations(prev => [conv, ...prev])
    setCurrentId(newId)
    persist(conv, true)
    return newId
  }, [currentId, persist])

  const loadConversation = useCallback((id: string): Conversation | null => {
    const conv = conversations.find(c => c.id === id) ?? null
    if (conv) setCurrentId(id)
    return conv
  }, [conversations])

  const deleteConversation = useCallback((id: string) => {
    const pending = saveTimers.current.get(id)
    if (pending) { clearTimeout(pending); saveTimers.current.delete(id) }

    setConversations(prev => prev.filter(c => c.id !== id))
    if (currentId === id) {
      setCurrentId(null)
    }
    if (userId) {
      apiClient.deleteConversationRemote(userId, id).catch(err => console.error('Failed to delete conversation:', err))
    }
  }, [currentId, userId])

  const renameConversation = useCallback((id: string, title: string) => {
    const trimmed = title.trim()
    if (!trimmed) return
    let updated: Conversation | undefined
    setConversations(prev =>
      prev.map(c => {
        if (c.id !== id) return c
        updated = { ...c, title: trimmed, customTitle: true, updatedAt: Date.now() }
        return updated
      })
    )
    if (updated) persist(updated, true)
  }, [persist])

  const assignToProject = useCallback((id: string, projectId: string | null) => {
    let updated: Conversation | undefined
    setConversations(prev =>
      prev.map(c => {
        if (c.id !== id) return c
        updated = { ...c, projectId, updatedAt: Date.now() }
        return updated
      })
    )
    if (updated) persist(updated, true)
  }, [persist])

  const togglePin = useCallback((id: string) => {
    let updated: Conversation | undefined
    setConversations(prev =>
      prev.map(c => {
        if (c.id !== id) return c
        updated = { ...c, pinned: !c.pinned }
        return updated
      })
    )
    if (updated) persist(updated, true)
  }, [persist])

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
