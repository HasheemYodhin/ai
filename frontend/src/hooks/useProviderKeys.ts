import { useState, useEffect, useCallback } from 'react'
import { apiClient } from '@/api/client'

export interface ProviderKeyStatus {
  provider: string
  hasKey: boolean
}

interface UseProviderKeysReturn {
  keys: ProviderKeyStatus[]
  isLoading: boolean
  error: string | null
  reload: () => void
}

/** Loads provider API-key status (set or not — never the values) from /v1/agent/keys. */
export function useProviderKeys(enabled: boolean): UseProviderKeysReturn {
  const [keys, setKeys] = useState<ProviderKeyStatus[]>([])
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
      .fetchProviderKeys(controller.signal)
      .then(setKeys)
      .catch(err => {
        if (err.name === 'AbortError') return
        setError(err.message ?? 'Failed to load API key status')
      })
      .finally(() => setIsLoading(false))

    return () => controller.abort()
  }, [enabled, reloadKey])

  return { keys, isLoading, error, reload }
}
