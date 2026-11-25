import { useDialogFocus } from '@/hooks/useDialogFocus'
import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import { useSettings, type AppSettings } from '@/hooks/useSettings'
import { useTheme } from '@/hooks/useTheme'
import { useModels } from '@/hooks/useModels'
import { useMcpStatus } from '@/hooks/useMcpStatus'
import { useProviderKeys } from '@/hooks/useProviderKeys'
import { useAuth } from '@/hooks/useAuth'
import { apiClient } from '@/api/client'
import { ACCENT_PRESETS, applyAccent, normalizeAccent } from '@/lib/accent'
import { EFFORT_TIERS, modelDisplayName, providerLabel } from '@/lib/models'
import { loadUsageStats, type UsageStats } from '@/lib/usageStats'
import { cn } from '@/lib/utils'
import { ApiKeyPromptModal } from './ApiKeyPromptModal'
import type { ModelInfo } from '@/types'
import {
  X,
  RefreshCw,
  Eye,
  EyeOff,
  Globe,
  Sliders,
  MessageSquareCode,
  Settings as SettingsIcon,
  Database,
  Sun,
  Moon,
  Download,
  Trash2,
  Check,
  Search,
  KeyRound,
  Plug,
  Wrench,
  BarChart3,
  Loader2,
  ShieldCheck,
  Bot,
  BrainCircuit,
  Bell,
} from 'lucide-react'

interface SettingsModalProps {
  isOpen: boolean
  onClose: () => void
}

type TabType = 'general' | 'model' | 'prompt' | 'keys' | 'tools' | 'usage' | 'data' | 'permissions' | 'agent' | 'memory'

const KEY_PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  google: 'Google',
  nvidia: 'NVIDIA',
  huggingface: 'Hugging Face',
}

const TIER_STYLES: Record<string, string> = {
  low: 'bg-gray-400/15 text-text-tertiary dark:text-text-dark-tertiary',
  medium: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
  high: 'bg-violet-500/15 text-violet-600 dark:text-violet-400',
  xhigh: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  max: 'bg-accent/15 text-accent',
}

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const { settings, updateSettings, resetSettings } = useSettings()
  const { theme, setTheme } = useTheme()
  const { models, isLoading: modelsLoading, reload: reloadModels } = useModels()
  const [activeTab, setActiveTab] = useState<TabType>('general')
  const [localSettings, setLocalSettings] = useState<AppSettings>(settings)
  const [showApiKey, setShowApiKey] = useState(false)
  const [isSavedAlert, setIsSavedAlert] = useState(false)
  const [modelSearch, setModelSearch] = useState('')
  const [stopInput, setStopInput] = useState(settings.stop.join(', '))

  // The dialog edits a working copy that Save writes back. It stays mounted
  // while closed, so refresh the copy each time it opens; otherwise a model or
  // effort picked in the header since the last open would be overwritten by
  // the stale copy on Save. (Adjusting state during render is React's
  // recommended way to reset state when a prop changes.)
  const [wasOpen, setWasOpen] = useState(isOpen)
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen)
    if (isOpen) {
      setLocalSettings(settings)
      setStopInput(settings.stop.join(', '))
    }
  }
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({})
  const [revealedKeys, setRevealedKeys] = useState<Record<string, boolean>>({})
  const [keyBusy, setKeyBusy] = useState<string | null>(null)
  const [keySaveError, setKeySaveError] = useState<string | null>(null)
  const [keyPromptModel, setKeyPromptModel] = useState<ModelInfo | null>(null)
  const [selectedModelForKey, setSelectedModelForKey] = useState('')

  const handleAddModelKeyClick = () => {
    const m = models.find(x => x.id === selectedModelForKey)
    if (m) {
      setKeyPromptModel(m)
      setSelectedModelForKey('')
    }
  }

  // /v1/agent/keys and /v1/mcp/* are admin-only; regular users get an
  // explanation instead of "Failed to load ... (status 403)".
  const { isAdmin, currentUser } = useAuth()
  const { keys: providerKeys, isLoading: keysLoading, error: keysError, reload: reloadKeys } =
    useProviderKeys(isAdmin && isOpen && activeTab === 'keys')

  const { servers: mcpServers, isLoading: mcpLoading, error: mcpError, reload: reloadMcp } =
    useMcpStatus(isAdmin && isOpen && activeTab === 'tools')

  // Usage and chats live on the server, so load them when the tab is opened.
  const [usageStats, setUsageStats] = useState<UsageStats | null>(null)
  const [usageError, setUsageError] = useState<string | null>(null)
  const [dataBusy, setDataBusy] = useState<'export' | 'clear' | null>(null)
  const [dataError, setDataError] = useState<string | null>(null)
  useEffect(() => {
    if (!isOpen || activeTab !== 'usage' || !currentUser) return
    const controller = new AbortController()
    setUsageError(null)
    loadUsageStats(currentUser.id, controller.signal)
      .then(setUsageStats)
      .catch(err => { if ((err as Error).name !== 'AbortError') setUsageError((err as Error).message || 'Could not load usage') })
    return () => controller.abort()
  }, [isOpen, activeTab, currentUser])

  // Hooks must run on every render regardless of `isOpen` — computing this
  // here (before the early return below) keeps the hook count stable across
  // closed/open renders. Putting it after `if (!isOpen) return null` was a
  // Rules-of-Hooks violation: React saw a different number of hooks fire
  // between the closed and open renders and threw, blanking the whole app
  // the moment Settings was opened.
  const currentModel = models.find(m => m.id === localSettings.model)
  const filteredGrouped = useMemo(() => {
    const q = modelSearch.trim().toLowerCase()
    const filtered = q
      ? models.filter(m => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q) || m.provider.toLowerCase().includes(q))
      : models
    const groups: Record<string, typeof models> = {}
    for (const m of filtered) {
      (groups[m.provider] ??= []).push(m)
    }
    return groups
  }, [models, modelSearch])

  // Theme buttons apply instantly as a preview. Remember the theme the modal
  // opened with so Cancel / ✕ / Escape / outside click can restore it; only
  // Save keeps the new one.
  const themeOnOpenRef = useRef(theme)
  useEffect(() => {
    if (isOpen) themeOnOpenRef.current = theme
    // Only when the modal opens; later theme changes are previews.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen])
  const handleDismiss = useCallback(() => {
    setTheme(themeOnOpenRef.current)
    applyAccent(settings.accentColor)
    onClose()
  }, [onClose, setTheme, settings.accentColor])

  const dialogRef = useDialogFocus(isOpen, handleDismiss)

  // The accent previews live while Settings is open; Save keeps it and Cancel restores the saved one.
  useEffect(() => {
    if (isOpen) applyAccent(localSettings.accentColor)
  }, [isOpen, localSettings.accentColor])

  if (!isOpen) return null

  const handleSaveKey = async (provider: string) => {
    const value = (keyInputs[provider] ?? '').trim()
    if (!value) return
    setKeyBusy(provider)
    setKeySaveError(null)
    try {
      await apiClient.setProviderKey(provider, value)
      setKeyInputs(prev => ({ ...prev, [provider]: '' }))
      reloadKeys()
    } catch (err) {
      setKeySaveError((err as Error).message || 'Failed to save key')
    } finally {
      setKeyBusy(null)
    }
  }

  const handleDeleteKey = async (provider: string) => {
    if (!confirm(`Remove the ${KEY_PROVIDER_LABELS[provider] ?? provider} API key?`)) return
    setKeyBusy(provider)
    setKeySaveError(null)
    try {
      await apiClient.deleteProviderKey(provider)
      reloadKeys()
    } catch (err) {
      setKeySaveError((err as Error).message || 'Failed to remove key')
    } finally {
      setKeyBusy(null)
    }
  }

  const handleSave = () => {
    themeOnOpenRef.current = theme
    const stop = stopInput.split(',').map(s => s.trim()).filter(Boolean)
    updateSettings({ ...localSettings, stop })
    setIsSavedAlert(true)
    setTimeout(() => {
      setIsSavedAlert(false)
      onClose()
    }, 800)
  }

  const handleReset = () => {
    resetSettings()
    setTimeout(() => {
      const stored = localStorage.getItem('dabba-settings')
      if (stored) {
        const parsed = JSON.parse(stored)
        setLocalSettings(parsed)
        setStopInput((parsed.stop ?? []).join(', '))
      }
    }, 50)
  }

  // Chats are stored on the server (not in this browser), so export and
  // delete go through the server.
  const handleExportAll = async () => {
    if (!currentUser) return
    setDataBusy('export'); setDataError(null)
    try {
      const conversations = await apiClient.fetchAllConversations(currentUser.id)
      if (!conversations.length) { setDataError('You have no conversations to export yet.'); return }
      const blob = new Blob([JSON.stringify(conversations, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `dabba-conversations-export-${Date.now()}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setDataError((err as Error).message || 'Export failed')
    } finally {
      setDataBusy(null)
    }
  }

  const handleClearHistory = async () => {
    if (!currentUser) return
    if (!confirm('Delete all conversations in this account? They are removed from the Dabba server and from every device you use. This cannot be undone.')) return
    setDataBusy('clear'); setDataError(null)
    try {
      const conversations = await apiClient.fetchConversations(currentUser.id)
      let failed = 0
      // A few at a time, so a long history doesn't open dozens of requests at once.
      for (let i = 0; i < conversations.length; i += 4) {
        const results = await Promise.allSettled(
          conversations.slice(i, i + 4).map(conv => apiClient.deleteConversationRemote(currentUser.id, conv.id)),
        )
        failed += results.filter(result => result.status === 'rejected').length
      }
      if (failed) {
        setDataError(`${failed} of ${conversations.length} conversations could not be deleted. Try again.`)
        return
      }
      // Forget the copies this browser keeps (older versions saved chats here).
      localStorage.removeItem('dabba-conversations')
      localStorage.removeItem(`dabba-pending-conversations:${currentUser.id}`)
      localStorage.removeItem(`dabba_current_conversation_id_${currentUser.id}`)
      window.location.reload()
    } catch (err) {
      setDataError((err as Error).message || 'Could not delete conversations')
    } finally {
      setDataBusy(null)
    }
  }

  const selectPresetPrompt = (preset: string) => {
    setLocalSettings(prev => ({ ...prev, systemPrompt: preset }))
  }

  const promptPresets = [
    { name: 'Dabba Assistant', prompt: 'You are Dabba, a production-grade custom transformer assistant.' },
    { name: 'Senior Developer', prompt: 'You are an expert Senior Software Engineer. Provide concise, clean, production-grade code snippets with minimal explanation.' },
    { name: 'Creative Writer', prompt: 'You are a professional creative writer. Craft engaging, elegant prose with rich imagery.' },
    { name: 'Socratic Teacher', prompt: 'You are a thoughtful teacher. Help the user learn by asking guiding questions rather than giving direct answers.' },
  ]

  const navItem = (tab: TabType, icon: React.ReactNode, label: string) => (
    <button
      onClick={() => setActiveTab(tab)}
      className={`flex w-auto flex-shrink-0 items-center gap-2.5 whitespace-nowrap px-3 py-2.5 rounded-xl text-xs font-semibold transition-all md:w-full ${
        activeTab === tab
          ? 'bg-accent/15 dark:bg-accent/25 text-accent border border-accent/20'
          : 'text-text-secondary hover:bg-surface dark:hover:bg-surface-dark-tertiary border border-transparent'
      }`}
    >
      {icon}
      {label}
    </button>
  )

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/40 animate-fade-in sm:items-center">
      <div
        className="fixed inset-0"
        onClick={handleDismiss}
      />

      {/* Claude-style 2-Column Dialog Panel */}
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Settings" tabIndex={-1} className="bg-surface dark:bg-surface-dark-secondary max-w-3xl w-full h-[100dvh] sm:h-[640px] sm:max-h-[calc(100dvh-2rem)] sm:rounded-2xl overflow-hidden relative z-10 sm:border border-border dark:border-border-dark shadow-xl sm:m-4 flex flex-col md:flex-row">

        {/* Left Column: Navigation Sidebar */}
        <div className="w-full flex-shrink-0 border-b border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary p-3 flex flex-col md:w-[200px] md:justify-between md:border-b-0 md:border-r md:p-4">
          <div className="min-w-0 space-y-3 md:space-y-6">
            <div className="flex items-center justify-between gap-2 px-2 py-1">
              <div className="flex items-center gap-2">
                <SettingsIcon className="w-5 h-5 text-accent" />
                <span className="font-semibold text-sm tracking-tight text-text-primary dark:text-text-dark-primary">
                  Dabba Settings
                </span>
              </div>
              {/* Close lives here on phones, where the tab strip sits above the page header. */}
              <button
                onClick={handleDismiss}
                aria-label="Close settings"
                className="flex h-9 w-9 items-center justify-center rounded-lg text-text-secondary hover:bg-surface-tertiary dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary md:hidden"
              >
                <X className="w-4.5 h-4.5" />
              </button>
            </div>

            <nav aria-label="Settings sections" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 scrollbar-thin md:mx-0 md:block md:space-y-1 md:overflow-visible md:px-0 md:pb-0">
              {navItem('general', <Globe className="w-4 h-4" />, 'General')}
              {navItem('model', <Sliders className="w-4 h-4" />, 'Model & Params')}
              {navItem('prompt', <MessageSquareCode className="w-4 h-4" />, 'System Prompts')}
              {navItem('keys', <KeyRound className="w-4 h-4" />, 'API Keys')}
              {navItem('tools', <Plug className="w-4 h-4" />, 'Tools (MCP)')}
              {navItem('permissions', <ShieldCheck className="w-4 h-4" />, 'Permissions & Safety')}
              {navItem('agent', <Bot className="w-4 h-4" />, 'Agent Behavior')}
              {navItem('memory', <BrainCircuit className="w-4 h-4" />, 'Memory')}
              {navItem('usage', <BarChart3 className="w-4 h-4" />, 'Usage')}
              {navItem('data', <Database className="w-4 h-4" />, 'Data Controls')}
            </nav>
          </div>

          <button
            onClick={handleReset}
            className="hidden items-center justify-center gap-2 text-[11px] text-text-tertiary hover:text-text-secondary px-3 py-2.5 rounded-xl hover:bg-surface dark:hover:bg-surface-dark-tertiary transition-colors border border-transparent md:flex"
            title="Reset to factory defaults"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Reset Defaults
          </button>
        </div>

        {/* Right Column: Tab View Content */}
        <div className="flex-1 min-h-0 min-w-0 flex flex-col bg-surface dark:bg-surface-dark-secondary overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 sm:px-6 sm:py-4.5 border-b border-border dark:border-border-dark">
            <h3 className="font-semibold text-sm text-text-primary dark:text-text-dark-primary capitalize">
              {activeTab === 'model' ? 'Model & Parameters'
                : activeTab === 'prompt' ? 'System Instructions'
                : activeTab === 'keys' ? 'Provider API Keys'
                : activeTab === 'tools' ? 'MCP Servers & Tools'
                : activeTab === 'usage' ? 'Usage Statistics'
                : activeTab === 'permissions' ? 'Permissions & Safety'
                : activeTab === 'agent' ? 'Agent Behavior'
                : activeTab === 'memory' ? 'Persistent Memory'
                : activeTab + ' settings'}
            </h3>
            <button
              onClick={handleDismiss}
              aria-label="Close settings"
              className="hidden p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors md:block"
            >
              <X className="w-4.5 h-4.5" />
            </button>
          </div>

          {/* Content Pane */}
          <div className="flex-1 overflow-y-auto scrollbar-thin p-4 sm:p-6 space-y-6">

            {/* General Tab */}
            {activeTab === 'general' && (
              <div className="space-y-5 animate-fade-in">
                <div className="space-y-2">
                  <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                    Appearance Theme
                  </label>
                  <div className="grid grid-cols-2 gap-3 max-w-sm">
                    <button
                      onClick={() => setTheme('light')}
                      className={`flex items-center justify-center gap-2 p-3 rounded-xl border text-xs font-semibold transition-all ${
                        theme === 'light'
                          ? 'bg-surface dark:bg-surface-dark-tertiary border-accent/40 text-accent shadow-sm'
                          : 'bg-transparent border-border dark:border-border-dark text-text-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
                      }`}
                    >
                      <Sun className="w-4 h-4" />
                      Light Theme
                    </button>
                    <button
                      onClick={() => setTheme('dark')}
                      className={`flex items-center justify-center gap-2 p-3 rounded-xl border text-xs font-semibold transition-all ${
                        theme === 'dark'
                          ? 'bg-surface-dark-tertiary border-accent/40 text-accent shadow-sm'
                          : 'bg-transparent border-border dark:border-border-dark text-text-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
                      }`}
                    >
                      <Moon className="w-4 h-4" />
                      Dark Theme
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <label id="accent-color-label" className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                    Accent color
                  </label>
                  <div role="radiogroup" aria-labelledby="accent-color-label" className="flex flex-wrap items-center gap-2.5">
                    {ACCENT_PRESETS.map(preset => {
                      const selected = normalizeAccent(localSettings.accentColor) === preset.hex
                      return (
                        <button
                          key={preset.id}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          aria-label={preset.name}
                          title={preset.name}
                          onClick={() => setLocalSettings(prev => ({ ...prev, accentColor: preset.hex }))}
                          style={{ backgroundColor: preset.hex }}
                          className={cn(
                            'flex h-8 w-8 items-center justify-center rounded-full ring-offset-2 ring-offset-surface transition-shadow dark:ring-offset-surface-dark-secondary',
                            'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-text-primary dark:focus-visible:outline-text-dark-primary',
                            selected ? 'ring-2 ring-text-primary dark:ring-text-dark-primary' : 'hover:ring-2 hover:ring-border dark:hover:ring-border-dark',
                          )}
                        >
                          {selected && <Check className="h-4 w-4 text-white" aria-hidden="true" />}
                        </button>
                      )
                    })}
                    <label className="flex items-center gap-2 rounded-full border border-border px-3 py-1.5 text-xs font-medium text-text-secondary dark:border-border-dark dark:text-text-dark-secondary">
                      <input
                        type="color"
                        aria-label="Custom color"
                        value={normalizeAccent(localSettings.accentColor)}
                        onChange={event => setLocalSettings(prev => ({ ...prev, accentColor: event.target.value }))}
                        className="h-5 w-5 cursor-pointer rounded border-0 bg-transparent p-0"
                      />
                      Custom
                    </label>
                  </div>
                  <p className="text-[11px] text-text-tertiary dark:text-text-dark-tertiary">
                    Used for buttons, links and highlights. Very light colors are darkened so text stays readable.
                  </p>
                </div>

                <div className="space-y-4 pt-3 border-t border-border dark:border-border-dark">
                  <label className="flex items-center justify-between gap-3 pt-2">
                    <span className="text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                      Stream responses
                    </span>
                    <Toggle
                      label="Stream responses"
                      checked={localSettings.streaming}
                      onChange={v => setLocalSettings(prev => ({ ...prev, streaming: v }))}
                    />
                  </label>
                  <label className="flex items-center justify-between gap-3 pt-3 border-t border-border dark:border-border-dark">
                    <span className="flex items-center gap-1.5 text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                      <Bell className="w-3.5 h-3.5" /> Desktop notifications
                    </span>
                    <Toggle
                      label="Desktop notifications"
                      checked={localSettings.desktopNotifications}
                      onChange={v => {
                        setLocalSettings(prev => ({ ...prev, desktopNotifications: v }))
                        if (v && typeof Notification !== 'undefined' && Notification.permission === 'default') {
                          void Notification.requestPermission()
                        }
                      }}
                    />
                  </label>
                  <p className="text-[11px] text-text-tertiary dark:text-text-dark-tertiary leading-relaxed">
                    Get an OS notification when a Cowork run or background process finishes, fails, or gets interrupted. In-app banners always show regardless of this setting.
                  </p>
                </div>

                {/* Developer settings: rarely changed, and the wrong value
                    disconnects the app, so they sit behind a disclosure. */}
                <details className="pt-3 border-t border-border dark:border-border-dark group">
                  <summary className="cursor-pointer text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                    Advanced (developer)
                  </summary>
                  <div className="space-y-4 pt-3">
                  <div className="space-y-1.5">
                    <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                      API Server Base URL
                    </label>
                    <input
                      type="text"
                      value={localSettings.baseUrl}
                      onChange={e => setLocalSettings(prev => ({ ...prev, baseUrl: e.target.value }))}
                      placeholder="Same server (recommended)"
                      className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors font-medium"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                      Authorization Key
                    </label>
                    <div className="relative">
                      <input
                        type={showApiKey ? 'text' : 'password'}
                        value={localSettings.apiKey}
                        onChange={e => setLocalSettings(prev => ({ ...prev, apiKey: e.target.value }))}
                        placeholder="Leave empty for local Dabba endpoint"
                        className="w-full pl-3.5 pr-10 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors font-mono"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiKey(!showApiKey)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 p-1.5 text-text-secondary hover:text-text-primary rounded-lg transition-colors"
                      >
                        {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  </div>
                </details>
              </div>
            )}

            {/* Model & Params Tab */}
            {activeTab === 'model' && (
              <div className="space-y-5 animate-fade-in">
                {/* Searchable model picker */}
                <div className="space-y-1.5">
                  <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                    Active Inference Engine
                  </label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-tertiary" />
                    <input
                      value={modelSearch}
                      onChange={e => setModelSearch(e.target.value)}
                      placeholder="Search models…"
                      className="w-full pl-8 pr-3 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
                    />
                  </div>

                  {/* Currently selected model — pinned so it never scrolls out of
                      view or gets hidden by a search filter that doesn't match it. */}
                  {currentModel && (
                    <div className="flex items-center justify-between gap-2 px-3 py-2 rounded-xl bg-accent/10 border border-accent/20">
                      <span className="flex items-center gap-1.5 min-w-0">
                        <span className="text-xs font-semibold text-accent/70 flex-shrink-0">Current</span>
                        <span className="text-xs font-medium text-accent truncate">{currentModel.name}</span>
                        <span className={`text-xs font-semibold px-1 py-0.5 rounded uppercase flex-shrink-0 ${TIER_STYLES[currentModel.tier] ?? TIER_STYLES.medium}`}>
                          {currentModel.tier}
                        </span>
                      </span>
                      <Check className="w-3.5 h-3.5 text-accent flex-shrink-0" />
                    </div>
                  )}

                  <div className="max-h-52 overflow-y-auto scrollbar-thin rounded-xl border border-border dark:border-border-dark">
                    {modelsLoading && models.length === 0 ? (
                      <div className="flex items-center justify-center gap-2 py-6 text-xs text-text-tertiary">
                        <Loader2 className="w-4 h-4 animate-spin" /> Loading models…
                      </div>
                    ) : Object.keys(filteredGrouped).length === 0 ? (
                      <div className="py-6 text-center text-xs text-text-tertiary">No models match “{modelSearch}”.</div>
                    ) : (
                      Object.entries(filteredGrouped).map(([provider, items]) => (
                        <div key={provider}>
                          <div className="px-3 py-1 text-xs font-semibold text-text-tertiary dark:text-text-dark-tertiary bg-surface-secondary dark:bg-surface-dark-tertiary">
                            {providerLabel(provider)}
                          </div>
                          {items.map(m => (
                            <button
                              key={m.id}
                              onClick={() => m.has_key ? setLocalSettings(prev => ({ ...prev, model: m.id })) : setKeyPromptModel(m)}
                              title={m.has_key ? m.description : `Click to add a ${providerLabel(m.provider)} API key`}
                              className={`w-full flex items-center justify-between gap-2 px-3 py-2 text-left transition-colors ${
                                !m.has_key ? 'opacity-80 hover:opacity-100 hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary' : localSettings.model === m.id ? 'bg-accent/10' : 'hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
                              }`}
                            >
                              <span className="flex items-center gap-1.5 min-w-0">
                                <span className={`text-xs font-medium truncate ${localSettings.model === m.id ? 'text-accent' : 'text-text-primary dark:text-text-dark-primary'}`}>
                                  {m.name}
                                </span>
                                <span className={`text-xs font-semibold px-1 py-0.5 rounded uppercase flex-shrink-0 ${TIER_STYLES[m.tier] ?? TIER_STYLES.medium}`}>
                                  {m.tier}
                                </span>
                                {!m.has_key && <KeyRound className="w-2.5 h-2.5 text-text-tertiary flex-shrink-0" />}
                              </span>
                              {localSettings.model === m.id && <Check className="w-3.5 h-3.5 text-accent flex-shrink-0" />}
                            </button>
                          ))}
                        </div>
                      ))
                    )}
                  </div>
                  <p className="text-xs text-text-tertiary">
                    Params below are remembered per-model — switching models restores what you last set for it.
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                    Reasoning Effort
                  </label>
                  <select
                    value={localSettings.effort}
                    onChange={e => setLocalSettings(prev => ({ ...prev, effort: e.target.value }))}
                    className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors font-semibold"
                  >
                    {EFFORT_TIERS.map(t => (
                      <option key={t.id} value={t.id}>{t.label} — {t.hint}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-4 pt-3 border-t border-border dark:border-border-dark">
                  <Slider label="Temperature" value={localSettings.temperature} min={0} max={1.5} step={0.1}
                    onChange={v => setLocalSettings(prev => ({ ...prev, temperature: v }))}
                    marks={['Deterministic (0.0)', 'Balanced (0.7)', 'Creative (1.5)']} />

                  <Slider label="Max Completion Output" value={localSettings.maxTokens} min={256} max={32768} step={256} unit=" tokens"
                    onChange={v => setLocalSettings(prev => ({ ...prev, maxTokens: v }))}
                    marks={['Short (256)', 'Standard (8192)', 'Extended (32768)']} />

                  <Slider label="Top P (nucleus sampling)" value={localSettings.topP} min={0} max={1} step={0.05}
                    onChange={v => setLocalSettings(prev => ({ ...prev, topP: v }))}
                    marks={['Narrow (0.0)', 'Default (0.9)', 'Full (1.0)']} />

                  <Slider label="Presence Penalty" value={localSettings.presencePenalty} min={-2} max={2} step={0.1}
                    onChange={v => setLocalSettings(prev => ({ ...prev, presencePenalty: v }))}
                    marks={['-2', '0', '+2']} />

                  <Slider label="Frequency Penalty" value={localSettings.frequencyPenalty} min={-2} max={2} step={0.1}
                    onChange={v => setLocalSettings(prev => ({ ...prev, frequencyPenalty: v }))}
                    marks={['-2', '0', '+2']} />

                  <div className="space-y-1.5">
                    <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                      Stop Sequences (comma-separated)
                    </label>
                    <input
                      value={stopInput}
                      onChange={e => setStopInput(e.target.value)}
                      placeholder="e.g. </end>, ###"
                      className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors font-mono"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* System Prompts Tab */}
            {activeTab === 'prompt' && (
              <div className="space-y-4 animate-fade-in">
                <div className="space-y-1.5">
                  <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                    Model Persona Instructions
                  </label>
                  <textarea
                    value={localSettings.systemPrompt}
                    onChange={e => setLocalSettings(prev => ({ ...prev, systemPrompt: e.target.value }))}
                    placeholder="Provide system instructions that format and direct assistant behavior..."
                    rows={6}
                    className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 resize-none scrollbar-thin font-medium leading-relaxed"
                  />
                </div>

                <div className="space-y-2 pt-2 border-t border-border dark:border-border-dark">
                  <label className="block text-xs font-semibold text-text-tertiary">
                    Quick Preset Personas
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {promptPresets.map((preset) => (
                      <button
                        key={preset.name}
                        onClick={() => selectPresetPrompt(preset.prompt)}
                        className={`text-xs px-3 py-1.5 rounded-xl border transition-all ${
                          localSettings.systemPrompt === preset.prompt
                            ? 'bg-accent/15 border-accent text-accent'
                            : 'bg-surface-tertiary hover:bg-surface dark:bg-surface-dark-tertiary dark:hover:bg-surface-dark border-border dark:border-border-dark text-text-secondary hover:text-text-primary'
                        }`}
                      >
                        {preset.name}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* API Keys Tab */}
            {activeTab === 'keys' && isAdmin && (
              <div className="space-y-4 animate-fade-in">
                <p className="text-xs text-text-secondary dark:text-text-dark-secondary leading-relaxed">
                  Keys are stored server-side (in <code className="font-mono text-[11px]">cli_config.yaml</code>) and used for any model
                  from that provider — the same store the CLI's <code className="font-mono text-[11px]">/keys set</code> command writes to.
                  Setting a key takes effect immediately, no restart needed.
                </p>

                {keysLoading && providerKeys.length === 0 ? (
                  <div className="flex items-center justify-center gap-2 py-8 text-xs text-text-tertiary">
                    <Loader2 className="w-4 h-4 animate-spin" /> Loading key status…
                  </div>
                ) : keysError ? (
                  <div className="p-3 rounded-xl bg-red-500/5 border border-red-500/10 text-xs text-red-500">{keysError}</div>
                ) : (
                  <div className="space-y-3">
                    {providerKeys.map(({ provider, hasKey }) => (
                      <div key={provider} className="p-3.5 rounded-2xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-text-primary dark:text-text-dark-primary">
                            {KEY_PROVIDER_LABELS[provider] ?? provider}
                          </span>
                          <span className={cn(
                            'text-xs font-semibold px-1.5 py-0.5 rounded uppercase',
                            hasKey ? 'bg-green-500/15 text-green-600 dark:text-green-400' : 'bg-surface-tertiary dark:bg-surface-dark text-text-tertiary'
                          )}>
                            {hasKey ? 'Set' : 'Not set'}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <div className="relative flex-1">
                            <input
                              type={revealedKeys[provider] ? 'text' : 'password'}
                              value={keyInputs[provider] ?? ''}
                              onChange={e => setKeyInputs(prev => ({ ...prev, [provider]: e.target.value }))}
                              onKeyDown={e => e.key === 'Enter' && handleSaveKey(provider)}
                              placeholder={hasKey ? 'Replace key…' : 'Paste API key…'}
                              className="w-full pl-3 pr-9 py-2 text-xs rounded-lg glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors font-mono"
                            />
                            <button
                              type="button"
                              onClick={() => setRevealedKeys(prev => ({ ...prev, [provider]: !prev[provider] }))}
                              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-text-tertiary hover:text-text-primary rounded-md transition-colors"
                            >
                              {revealedKeys[provider] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                            </button>
                          </div>
                          <button
                            onClick={() => handleSaveKey(provider)}
                            disabled={keyBusy === provider || !(keyInputs[provider] ?? '').trim()}
                            className="px-3 py-2 rounded-lg text-xs font-semibold bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors flex-shrink-0"
                          >
                            {keyBusy === provider ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Save'}
                          </button>
                          {hasKey && (
                            <button
                              onClick={() => handleDeleteKey(provider)}
                              disabled={keyBusy === provider}
                              aria-label="Remove key" title="Remove key"
                              className="p-2 rounded-lg hover:bg-red-500/10 text-text-tertiary hover:text-red-500 disabled:opacity-40 transition-colors flex-shrink-0"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    ))}

                    {/* Section to configure model-specific key */}
                    <div className="pt-4 border-t border-border dark:border-border-dark space-y-2 mt-4">
                      <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                        Configure key for a specific model
                      </label>
                      <div className="flex gap-2">
                        <select
                          value={selectedModelForKey}
                          onChange={e => setSelectedModelForKey(e.target.value)}
                          className="flex-1 px-3 py-2 text-xs rounded-xl glass-input border border-border dark:border-border-dark outline-none text-text-primary dark:text-text-dark-primary bg-surface dark:bg-surface-dark-secondary focus:border-accent/40 transition-colors"
                        >
                          <option value="">Select a model...</option>
                          {models
                            .filter(m => m.provider !== 'dabba' && m.provider !== 'ollama')
                            .map(m => (
                              <option key={m.id} value={m.id}>
                                {m.name} ({providerLabel(m.provider)})
                              </option>
                            ))}
                        </select>
                        <button
                          onClick={handleAddModelKeyClick}
                          disabled={!selectedModelForKey}
                          className="px-4 py-2 rounded-xl text-xs font-semibold bg-accent hover:bg-accent-hover text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                          Configure Key
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {keySaveError && (
                  <p className="text-xs text-red-500">{keySaveError}</p>
                )}
              </div>
            )}

            {/* Tools (MCP) Tab */}
            {(activeTab === 'keys' || activeTab === 'tools') && !isAdmin && (
              <div className="p-3.5 rounded-2xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary text-xs text-text-secondary dark:text-text-dark-secondary leading-relaxed animate-fade-in">
                {activeTab === 'keys'
                  ? 'Provider API keys are managed by the workspace owner, for example as server environment variables. Models with a key configured are ready to use from the model picker.'
                  : 'MCP tools are managed by the workspace owner.'}
              </div>
            )}
            {activeTab === 'tools' && isAdmin && (
              <div className="space-y-4 animate-fade-in">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-text-secondary dark:text-text-dark-secondary">
                    Servers configured in <code className="font-mono text-[11px]">mcp_servers.json</code> on the Dabba server.
                  </p>
                  <button
                    onClick={reloadMcp}
                    className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-tertiary transition-colors"
                    aria-label="Refresh" title="Refresh"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                  </button>
                </div>

                {mcpLoading ? (
                  <div className="flex items-center justify-center gap-2 py-8 text-xs text-text-tertiary">
                    <Loader2 className="w-4 h-4 animate-spin" /> Loading MCP status…
                  </div>
                ) : mcpError ? (
                  <div className="p-4 rounded-xl bg-red-500/5 border border-red-500/10 text-xs text-red-500">
                    {mcpError}
                  </div>
                ) : mcpServers.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-10 text-text-tertiary">
                    <Plug className="w-8 h-8 mb-2 opacity-30" />
                    <p className="text-xs">No MCP servers configured.</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {mcpServers.map(s => (
                      <div key={s.name} className="p-3 rounded-xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className={`w-1.5 h-1.5 rounded-full ${s.connected ? 'bg-green-500' : 'bg-gray-400'}`} />
                            <span className="text-xs font-semibold text-text-primary dark:text-text-dark-primary">{s.name}</span>
                          </div>
                          <span className="text-xs text-text-tertiary">{s.connected ? 'connected' : 'disconnected'}</span>
                        </div>
                        <p className="text-xs font-mono text-text-tertiary mt-1 truncate">{s.command} {s.args?.join(' ')}</p>
                        {s.tools?.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {s.tools.map(t => (
                              <span key={t} className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded bg-surface dark:bg-surface-dark text-text-secondary dark:text-text-dark-secondary">
                                <Wrench className="w-2.5 h-2.5" /> {t}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Permissions & Safety Tab */}
            {activeTab === 'permissions' && (
              <div className="space-y-5 animate-fade-in">
                <div className="space-y-2">
                  <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                    Default tool-approval mode
                  </label>
                  <div className="grid grid-cols-3 gap-2 max-w-md">
                    {(['ask', 'allow', 'deny'] as const).map(mode => (
                      <button
                        key={mode}
                        onClick={() => setLocalSettings(prev => ({ ...prev, defaultPermissionMode: mode }))}
                        className={cn(
                          'p-3 rounded-xl border text-xs font-semibold capitalize transition-all',
                          localSettings.defaultPermissionMode === mode
                            ? 'bg-surface dark:bg-surface-dark-tertiary border-accent/40 text-accent shadow-sm'
                            : 'bg-transparent border-border dark:border-border-dark text-text-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
                        )}
                      >
                        {mode}
                      </button>
                    ))}
                  </div>
                  <p className="text-[11px] text-text-tertiary dark:text-text-dark-tertiary leading-relaxed">
                    "Ask" pauses for your approval before dangerous tool calls (shell commands, file writes). "Allow" runs everything automatically. "Deny" blocks dangerous tools outright. Cowork and scheduled runs always run with tools enabled regardless of this setting.
                  </p>
                </div>

                <div className="p-4 rounded-2xl bg-surface-secondary dark:bg-surface-dark-tertiary border border-border dark:border-border-dark space-y-2">
                  <h4 className="text-xs font-semibold text-text-primary dark:text-text-dark-primary flex items-center gap-1.5">
                    <ShieldCheck className="w-4 h-4 text-accent" />
                    Git safety rules (always on)
                  </h4>
                  <ul className="text-xs text-text-secondary dark:text-text-dark-secondary leading-relaxed list-disc pl-4 space-y-1">
                    <li>Direct commits to <code className="text-[11px]">main</code>/<code className="text-[11px]">master</code>/<code className="text-[11px]">develop</code>/<code className="text-[11px]">dev</code> are blocked outright — no setting overrides this.</li>
                    <li>Force-pushing to a protected branch is blocked outright.</li>
                    <li>Force-pushing to any other branch, or a plain push to a protected branch, requires explicit confirmation even in "Allow" mode.</li>
                  </ul>
                </div>
              </div>
            )}

            {/* Agent Behavior Tab */}
            {activeTab === 'agent' && (
              <div className="space-y-5 animate-fade-in">
                <label className="flex items-center justify-between gap-3">
                  <div>
                    <span className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Plan before acting, by default</span>
                    <span className="block text-[11px] text-text-tertiary dark:text-text-dark-tertiary mt-0.5">Propose a multi-step plan and wait for your approval before running it, on every agent turn (not just when the chat "Plan mode" chip is on).</span>
                  </div>
                  <Toggle
                    label="Plan before acting by default"
                    checked={localSettings.planModeDefault}
                    onChange={v => setLocalSettings(prev => ({ ...prev, planModeDefault: v }))}
                  />
                </label>

                <label className="flex items-center justify-between gap-3 pt-3 border-t border-border dark:border-border-dark">
                  <div>
                    <span className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Deferred tool loading</span>
                    <span className="block text-[11px] text-text-tertiary dark:text-text-dark-tertiary mt-0.5">Only load a small set of tool schemas up front; the model searches for the rest as needed. Reduces prompt size when many tools/connectors are registered.</span>
                  </div>
                  <Toggle
                    label="Deferred tool loading"
                    checked={localSettings.useToolSearch}
                    onChange={v => setLocalSettings(prev => ({ ...prev, useToolSearch: v }))}
                  />
                </label>

                <div className="space-y-1.5 pt-3 border-t border-border dark:border-border-dark">
                  <div className="flex justify-between items-center text-xs">
                    <span className="font-semibold text-text-secondary dark:text-text-dark-secondary">Max steps per turn</span>
                    <span className="font-semibold text-accent">{localSettings.maxSteps ?? 'Backend default'}</span>
                  </div>
                  <input
                    type="range" min="0" max="100" step="5"
                    value={localSettings.maxSteps ?? 0}
                    onChange={e => {
                      const value = parseInt(e.target.value)
                      setLocalSettings(prev => ({ ...prev, maxSteps: value === 0 ? null : value }))
                    }}
                    className="w-full accent-accent bg-surface-tertiary dark:bg-surface-dark-tertiary h-1.5 rounded-lg cursor-pointer"
                  />
                  <p className="text-[11px] text-text-tertiary dark:text-text-dark-tertiary">0 = use the backend's own default instead of overriding it.</p>
                </div>

                <div className="space-y-1.5 pt-3 border-t border-border dark:border-border-dark">
                  <div className="flex justify-between items-center text-xs">
                    <span className="font-semibold text-text-secondary dark:text-text-dark-secondary">Context compaction threshold</span>
                    <span className="font-semibold text-accent">{Math.round(localSettings.contextCompactionThreshold * 100)}%</span>
                  </div>
                  <input
                    type="range" min="0.3" max="0.95" step="0.05"
                    value={localSettings.contextCompactionThreshold}
                    onChange={e => setLocalSettings(prev => ({ ...prev, contextCompactionThreshold: parseFloat(e.target.value) }))}
                    className="w-full accent-accent bg-surface-tertiary dark:bg-surface-dark-tertiary h-1.5 rounded-lg cursor-pointer"
                  />
                  <p className="text-[11px] text-text-tertiary dark:text-text-dark-tertiary">Older turns get LLM-summarized once the context fills past this fraction, so long tasks don't lose earlier context.</p>
                </div>

                <div className="space-y-1.5">
                  <div className="flex justify-between items-center text-xs">
                    <span className="font-semibold text-text-secondary dark:text-text-dark-secondary">Recent turns always kept verbatim</span>
                    <span className="font-semibold text-accent">{localSettings.contextCompactionKeepRecent}</span>
                  </div>
                  <input
                    type="range" min="2" max="20" step="1"
                    value={localSettings.contextCompactionKeepRecent}
                    onChange={e => setLocalSettings(prev => ({ ...prev, contextCompactionKeepRecent: parseInt(e.target.value) }))}
                    className="w-full accent-accent bg-surface-tertiary dark:bg-surface-dark-tertiary h-1.5 rounded-lg cursor-pointer"
                  />
                </div>
              </div>
            )}

            {/* Memory Tab */}
            {activeTab === 'memory' && <MemoryTabContent />}

            {/* Usage Tab */}
            {activeTab === 'usage' && !usageStats && (
              <div role={usageError ? 'alert' : 'status'} className="flex items-center justify-center gap-2 py-12 text-xs text-text-tertiary">
                {usageError ? <span className="text-red-500">{usageError}</span> : <><Loader2 className="w-4 h-4 animate-spin" /> Loading usage…</>}
              </div>
            )}
            {activeTab === 'usage' && usageStats && (
              <div className="space-y-5 animate-fade-in">
                <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-3">
                  <StatCard label="Conversations" value={usageStats.totalConversations} />
                  <StatCard label="Messages" value={usageStats.totalMessages} />
                  <StatCard label="Total Tokens" value={usageStats.totalTokens.toLocaleString()} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <StatCard label="Prompt Tokens" value={usageStats.promptTokens.toLocaleString()} />
                  <StatCard label="Completion Tokens" value={usageStats.completionTokens.toLocaleString()} />
                </div>

                <div className="space-y-2 pt-2 border-t border-border dark:border-border-dark">
                  <label className="block text-xs font-semibold text-text-tertiary">
                    Usage by Model
                  </label>
                  {usageStats.byModel.length === 0 ? (
                    <p className="text-xs text-text-tertiary py-4">No usage recorded yet — token counts appear here once the server reports them on a reply.</p>
                  ) : (
                    <div className="space-y-1.5">
                      {usageStats.byModel.map(m => {
                        const pct = usageStats.totalTokens ? Math.round((m.tokens / usageStats.totalTokens) * 100) : 0
                        return (
                          <div key={m.model} className="space-y-1">
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-medium text-text-primary dark:text-text-dark-primary">{modelDisplayName(m.model)}</span>
                              <span className="text-text-tertiary">{m.tokens.toLocaleString()} tok · {m.replies} replies</span>
                            </div>
                            <div className="h-1.5 rounded-full bg-surface-tertiary dark:bg-surface-dark-tertiary overflow-hidden">
                              <div className="h-full bg-accent rounded-full" style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
                <p className="text-xs text-text-tertiary">
                  Totals come from your Dabba server and cover every device you sign in on. They include the short requests Dabba makes to name your chats.
                </p>
              </div>
            )}

            {/* Data Controls Tab */}
            {activeTab === 'data' && (
              <div className="space-y-5 animate-fade-in">
                {dataError && <p role="alert" className="rounded-xl border border-red-500/25 bg-red-500/5 px-3 py-2 text-xs text-red-600 dark:text-red-400">{dataError}</p>}
                <div className="p-4 rounded-2xl bg-surface-secondary dark:bg-surface-dark-tertiary border border-border dark:border-border-dark space-y-2">
                  <h4 className="text-xs font-semibold text-text-primary dark:text-text-dark-primary flex items-center gap-1.5">
                    <Download className="w-4 h-4 text-accent" />
                    Export Conversations
                  </h4>
                  <p className="text-xs text-text-secondary dark:text-text-dark-secondary leading-relaxed">
                    Download all the conversations in this account as a single JSON file, as a backup or to use elsewhere.
                  </p>
                  <button
                    onClick={() => void handleExportAll()}
                    disabled={dataBusy !== null}
                    className="flex items-center gap-2 mt-2 px-4 py-2.5 rounded-xl text-xs font-semibold bg-surface dark:bg-surface-dark-tertiary hover:bg-accent/10 border border-border dark:border-border-dark hover:border-accent/30 text-text-primary dark:text-text-dark-primary transition-colors"
                  >
                    {dataBusy === 'export' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                    Export Conversations (.json)
                  </button>
                </div>

                <div className="p-4 rounded-2xl bg-red-500/5 dark:bg-red-500/10 border border-red-500/10 dark:border-red-500/20 space-y-2">
                  <h4 className="text-xs font-semibold text-red-500 flex items-center gap-1.5">
                    <Trash2 className="w-4 h-4" />
                    Danger Zone
                  </h4>
                  <p className="text-xs text-text-secondary dark:text-text-dark-secondary leading-relaxed">
                    Permanently delete every conversation in this account. They are removed from the Dabba server, so they disappear on all your devices too. This cannot be undone.
                  </p>
                  <button
                    onClick={() => void handleClearHistory()}
                    disabled={dataBusy !== null}
                    className="flex items-center gap-2 mt-2 px-4 py-2.5 rounded-xl text-xs font-semibold bg-red-500/10 hover:bg-red-500/25 border border-red-500/25 text-red-500 hover:text-white transition-all active:scale-[0.98]"
                  >
                    {dataBusy === 'clear' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                    Clear History & Reset
                  </button>
                </div>
              </div>
            )}

          </div>

          {/* Footer Controls */}
          <div className="px-4 py-3 sm:px-6 sm:py-4 border-t border-border dark:border-border-dark flex items-center justify-end gap-2 bg-surface-secondary dark:bg-surface-dark-tertiary">
            <button
              onClick={handleReset}
              title="Reset to factory defaults"
              className="mr-auto flex items-center gap-1.5 rounded-xl px-2 py-2 text-[11px] text-text-tertiary hover:text-text-secondary md:hidden"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Reset
            </button>
            {isSavedAlert ? (
              <span className="text-xs text-green-500 font-semibold flex items-center gap-1 animate-fade-in md:mr-auto">
                <Check className="w-4 h-4" />
                Settings Saved!
              </span>
            ) : null}

            <button
              onClick={handleDismiss}
              className="px-4 py-2 rounded-xl text-xs font-semibold hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-accent hover:bg-accent-hover text-white transition-colors"
            >
              Save Settings
            </button>
          </div>
        </div>

      </div>

      {keyPromptModel && (
        <ApiKeyPromptModal
          target={keyPromptModel.id}
          provider={keyPromptModel.provider}
          modelName={keyPromptModel.name}
          onClose={() => setKeyPromptModel(null)}
          onSaved={() => {
            setLocalSettings(prev => ({ ...prev, model: keyPromptModel.id }))
            reloadModels()
            if (activeTab === 'keys') {
              reloadKeys()
            }
          }}
        />
      )}
    </div>
  )
}

function Slider({ label, value, min, max, step, unit = '', marks, onChange }: {
  label: string; value: number; min: number; max: number; step: number; unit?: string
  marks: [string, string, string]; onChange: (v: number) => void
}) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center text-xs">
        <span className="font-semibold text-text-secondary dark:text-text-dark-secondary">{label}</span>
        <span className="font-semibold text-accent">{value}{unit}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full accent-accent bg-surface-tertiary dark:bg-surface-dark-tertiary h-1.5 rounded-lg cursor-pointer"
      />
      <div className="flex justify-between text-xs text-text-tertiary">
        {marks.map(m => <span key={m}>{m}</span>)}
      </div>
    </div>
  )
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}
      className={`relative w-9 h-5 rounded-full transition-colors flex-shrink-0 ${checked ? 'bg-accent' : 'bg-surface-tertiary dark:bg-surface-dark-tertiary'}`}
    >
      <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : ''}`} />
    </button>
  )
}

interface MemoryEntry { id: string; scope: string; key: string; content: string; updatedAt: number }

/** Lists/adds/deletes the facts Dabba remembers across sessions (MemoryService's "preference" scope). */
function MemoryTabContent() {
  const [memories, setMemories] = useState<MemoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [newFact, setNewFact] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setError('')
    try { setMemories(await apiClient.listMemories('preference')) }
    catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const addFact = async () => {
    const content = newFact.trim()
    if (!content || busy) return
    setBusy(true); setError('')
    try {
      await apiClient.saveMemory('preference', `fact-${Date.now()}`, content)
      setNewFact('')
      await refresh()
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  const removeFact = async (id: string) => {
    setMemories(prev => prev.filter(m => m.id !== id))
    try { await apiClient.deleteMemory(id) }
    catch (err) { setError((err as Error).message); await refresh() }
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <p className="text-xs text-text-secondary dark:text-text-dark-secondary leading-relaxed">
        Facts you've asked Dabba to remember — persisted across sessions and automatically included in every agent prompt.
      </p>
      <div className="flex items-center gap-2">
        <input
          value={newFact}
          onChange={e => setNewFact(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); void addFact() } }}
          placeholder="e.g. I prefer TypeScript over JavaScript"
          className="flex-1 px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
        />
        <button
          disabled={!newFact.trim() || busy}
          onClick={() => void addFact()}
          className="px-4 py-2.5 rounded-xl text-xs font-semibold bg-accent hover:bg-accent-hover disabled:opacity-40 text-white transition-colors"
        >
          Remember
        </button>
      </div>
      {error && <p className="text-xs text-red-500">{error}</p>}
      {loading ? (
        <div className="flex items-center justify-center py-10 text-text-tertiary"><Loader2 className="w-5 h-5 animate-spin" /></div>
      ) : memories.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-text-tertiary">
          <BrainCircuit className="w-9 h-9 mb-2 opacity-30" />
          <p className="text-sm font-medium">Nothing remembered yet</p>
        </div>
      ) : (
        <div className="space-y-2">
          {memories.map(m => (
            <div key={m.id} className="flex items-start gap-2 p-3 rounded-xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary">
              <span className="flex-1 text-xs text-text-primary dark:text-text-dark-primary leading-relaxed">{m.content}</span>
              <button aria-label="Remove memory" onClick={() => void removeFact(m.id)} className="p-1 rounded-md hover:bg-surface dark:hover:bg-surface-dark text-text-tertiary hover:text-red-500 transition-colors flex-shrink-0">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="p-3 rounded-xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary">
      <div className="text-lg font-semibold text-text-primary dark:text-text-dark-primary">{value}</div>
      <div className="text-xs text-text-tertiary">{label}</div>
    </div>
  )
}
