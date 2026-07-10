import { useState, useEffect, useCallback } from 'react'
import { apiClient } from '@/api/client'
import type { ModelInfo } from '@/types'
import { useSettings } from '@/hooks/useSettings'
import { FALLBACK_MODELS } from '@/lib/models'

interface UseModelsReturn {
  models: ModelInfo[]
  isLoading: boolean
  error: string | null
  reload: () => void
}

/**
 * Loads the model catalog from the Dabba server (/v1/agent/models).
 * Falls back to a small static list if the server is unreachable so the
 * picker is never empty. Re-fetches whenever the API base URL changes.
 */
export function useModels(): UseModelsReturn {
  const { settings } = useSettings()
  const [models, setModels] = useState<ModelInfo[]>(FALLBACK_MODELS)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const reload = useCallback(() => setReloadKey(k => k + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    setIsLoading(true)
    setError(null)

    apiClient
      .fetchModels(controller.signal)
      .then(catalog => {
        if (catalog.models?.length) {
          setModels(catalog.models)
        }
      })
      .catch(err => {
        if (err.name === 'AbortError') return
        setError(err.message ?? 'Failed to load models')
        setModels(FALLBACK_MODELS)
      })
      .finally(() => setIsLoading(false))

    return () => controller.abort()
  }, [settings.baseUrl, reloadKey])

  return { models, isLoading, error, reload }
}
