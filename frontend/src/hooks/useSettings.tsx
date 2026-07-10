import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react'
import { apiClient } from '@/api/client'

/** Generation params that can be remembered per-model. */
export interface ModelParams {
  temperature: number
  maxTokens: number
  effort: string
  topP: number
}

export interface AppSettings {
  baseUrl: string
  apiKey: string
  model: string
  effort: string
  temperature: number
  maxTokens: number
  topP: number
  presencePenalty: number
  frequencyPenalty: number
  stop: string[]
  streaming: boolean
  typingSpeed: number // ms delay per token on the server-side typewriter (informational)
  systemPrompt: string
  /** Remembered params keyed by model id — restored when you switch back. */
  modelDefaults: Record<string, ModelParams>
}

const DEFAULT_SETTINGS: AppSettings = {
  baseUrl: 'http://localhost:8080',
  apiKey: '',
  model: 'dabba-10m',
  effort: 'medium',
  temperature: 0.7,
  maxTokens: 256,
  topP: 0.9,
  presencePenalty: 0,
  frequencyPenalty: 0,
  stop: [],
  streaming: true,
  typingSpeed: 10,
  systemPrompt: 'You are Dabba, a production-grade custom transformer assistant.',
  modelDefaults: {},
}

interface SettingsContextType {
  settings: AppSettings
  updateSettings: (newSettings: Partial<AppSettings>) => void
  resetSettings: () => void
}

const SettingsContext = createContext<SettingsContextType>({
  settings: DEFAULT_SETTINGS,
  updateSettings: () => {},
  resetSettings: () => {},
})

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettingsState] = useState<AppSettings>(() => {
    try {
      const stored = localStorage.getItem('dabba-settings')
      if (stored) {
        return { ...DEFAULT_SETTINGS, ...JSON.parse(stored) }
      }
    } catch {
      // ignore
    }
    return DEFAULT_SETTINGS
  })

  // Sync settings with ApiClient
  useEffect(() => {
    apiClient.setBaseUrl(settings.baseUrl)
    apiClient.setApiKey(settings.apiKey)
    localStorage.setItem('dabba-settings', JSON.stringify(settings))
  }, [settings])

  const updateSettings = useCallback((newSettings: Partial<AppSettings>) => {
    setSettingsState(prev => {
      // Switching models: stash the current params under the old model, then
      // restore the new model's remembered params (if any).
      if (newSettings.model && newSettings.model !== prev.model) {
        const savedForOld: ModelParams = {
          temperature: prev.temperature,
          maxTokens: prev.maxTokens,
          effort: prev.effort,
          topP: prev.topP,
        }
        const modelDefaults = { ...prev.modelDefaults, [prev.model]: savedForOld }
        const restored = modelDefaults[newSettings.model]
        return {
          ...prev,
          ...newSettings,
          modelDefaults,
          ...(restored ? {
            temperature: restored.temperature,
            maxTokens: restored.maxTokens,
            effort: restored.effort,
            topP: restored.topP,
          } : {}),
        }
      }
      return { ...prev, ...newSettings }
    })
  }, [])

  const resetSettings = useCallback(() => {
    setSettingsState(DEFAULT_SETTINGS)
  }, [])

  return (
    <SettingsContext.Provider value={{ settings, updateSettings, resetSettings }}>
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  return useContext(SettingsContext)
}
