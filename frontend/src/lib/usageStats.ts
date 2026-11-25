import { apiClient, type ServerUsage } from '@/api/client'

export interface UsageStats {
  totalConversations: number
  totalMessages: number
  totalTokens: number
  promptTokens: number
  completionTokens: number
  limits: NonNullable<ServerUsage['limits']>
  byModel: { model: string; tokens: number; replies: number }[]
}

/**
 * Combines the server's recorded token usage with the conversation list.
 * Chats live on the server, so counts come from the (lightweight) list and
 * tokens from the usage the server recorded for each finished reply.
 */
export function buildUsageStats(
  usage: ServerUsage,
  conversations: { messageCount?: number; messages?: unknown[] }[],
): UsageStats {
  return {
    totalConversations: conversations.length,
    totalMessages: conversations.reduce((sum, conv) => sum + (conv.messageCount ?? conv.messages?.length ?? 0), 0),
    totalTokens: usage.totalTokens,
    promptTokens: usage.promptTokens,
    completionTokens: usage.completionTokens,
    limits: usage.limits ?? [],
    byModel: usage.byModel.map(({ model, tokens, replies }) => ({ model, tokens, replies })),
  }
}

export async function loadUsageStats(userId: string, signal?: AbortSignal): Promise<UsageStats> {
  const [usage, conversations] = await Promise.all([apiClient.fetchUsage(signal), apiClient.fetchConversations(userId, signal)])
  return buildUsageStats(usage, conversations)
}
