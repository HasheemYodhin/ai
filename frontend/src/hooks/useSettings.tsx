import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react'
import { apiClient, DEFAULT_API_URL } from '@/api/client'

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

  // Permissions & safety
  /** Default tool-approval mode sent with every agent turn: "ask" pauses for approval, "allow" runs everything, "deny" blocks dangerous tools outright. */
  defaultPermissionMode: 'ask' | 'allow' | 'deny'

  // Notifications
  /** Opt-in for OS-level desktop notifications on Cowork run completion / background process completion. In-app toasts always show regardless. */
  desktopNotifications: boolean

  // Agent behavior
  /** Propose-then-approve a multi-step plan by default, instead of only when the chat "Plan mode" chip is toggled on for that turn. */
  planModeDefault: boolean
  /** Defer full tool schemas until the model searches for them — cuts prompt size on a large tool registry. */
  useToolSearch: boolean
  /** Max LLM round-trips per turn before the agent stops itself. Null = leave the backend's own default alone. */
  maxSteps: number | null
  /** Fraction of the context window that triggers proactive LLM-based summarization of older turns. */
  contextCompactionThreshold: number
  /** Most recent conversation entries always kept verbatim, never folded into a summary. */
  contextCompactionKeepRecent: number
}

const DEFAULT_SETTINGS: AppSettings = {
  // Relative URLs work locally; Cloudflare Pages injects the Render URL at build time.
  baseUrl: DEFAULT_API_URL,
  apiKey: '',
  model: 'dabba',
  effort: 'medium',
  temperature: 0.7,
  maxTokens: 8192,
  topP: 0.9,
  presencePenalty: 0,
  frequencyPenalty: 0,
  stop: [],
  streaming: true,
  typingSpeed: 0,
  systemPrompt: 'You are Dabba, a production-grade custom transformer assistant.',
  modelDefaults: {},
  defaultPermissionMode: 'ask',
  desktopNotifications: false,
  planModeDefault: false,
  useToolSearch: false,
  maxSteps: null,
  contextCompactionThreshold: 0.75,
  contextCompactionKeepRecent: 6,
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
        const parsed = JSON.parse(stored) as Partial<AppSettings>
        // Migrate the old hardcoded default. Explicit non-default API URLs are preserved.
        if (parsed.model === 'dabba-10m') parsed.model = 'dabba'
        if (parsed.baseUrl === 'http://localhost:8080') parsed.baseUrl = DEFAULT_API_URL
        return {
          ...DEFAULT_SETTINGS,
          ...parsed,
          baseUrl: parsed.baseUrl || DEFAULT_API_URL,
        }
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
