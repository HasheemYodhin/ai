import type { Conversation } from '@/types'

export interface UsageStats {
  totalConversations: number
  totalMessages: number
  totalTokens: number
  promptTokens: number
  completionTokens: number
  byModel: { model: string; tokens: number; replies: number }[]
}

/** Reads conversation history straight from localStorage — same store useHistory uses. */
export function loadConversationsForUsage(): Conversation[] {
  try {
    const raw = localStorage.getItem('dabba-conversations')
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

export function computeUsageStats(conversations: Conversation[]): UsageStats {
  const byModel = new Map<string, { tokens: number; replies: number }>()
  let promptTokens = 0
  let completionTokens = 0
  let totalMessages = 0

  for (const conv of conversations) {
    for (const msg of conv.messages) {
      totalMessages++
      if (msg.role !== 'assistant' || !msg.usage) continue
      promptTokens += msg.usage.promptTokens
      completionTokens += msg.usage.completionTokens
      const key = msg.model ?? 'unknown'
      const entry = byModel.get(key) ?? { tokens: 0, replies: 0 }
      entry.tokens += msg.usage.totalTokens
      entry.replies += 1
      byModel.set(key, entry)
    }
  }

  return {
    totalConversations: conversations.length,
    totalMessages,
    totalTokens: promptTokens + completionTokens,
    promptTokens,
    completionTokens,
    byModel: Array.from(byModel.entries())
      .map(([model, v]) => ({ model, ...v }))
      .sort((a, b) => b.tokens - a.tokens),
  }
}
