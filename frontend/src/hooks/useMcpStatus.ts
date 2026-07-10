import { useState, useEffect, useCallback } from 'react'
import { apiClient } from '@/api/client'
import type { McpServer } from '@/types'

interface UseMcpStatusReturn {
  servers: McpServer[]
  isLoading: boolean
  error: string | null
  reload: () => void
}

/** Loads connected MCP servers + tools from /v1/mcp/status. Only fetch when a UI panel needs it. */
export function useMcpStatus(enabled: boolean): UseMcpStatusReturn {
  const [servers, setServers] = useState<McpServer[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const reload = useCallback(() => setReloadKey(k => k + 1), [])

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    setIsLoading(true)
    setError(null)

    apiClient
      .fetchMcpStatus(controller.signal)
      .then(data => setServers(data.servers ?? []))
      .catch(err => {
        if (err.name === 'AbortError') return
        setError(err.message ?? 'Failed to load MCP status')
      })
      .finally(() => setIsLoading(false))

    return () => controller.abort()
  }, [enabled, reloadKey])

  return { servers, isLoading, error, reload }
}
