import { useState, useMemo } from 'react'
import { useSettings, type AppSettings } from '@/hooks/useSettings'
import { useTheme } from '@/hooks/useTheme'
import { useModels } from '@/hooks/useModels'
import { useMcpStatus } from '@/hooks/useMcpStatus'
import { useProviderKeys } from '@/hooks/useProviderKeys'
import { apiClient } from '@/api/client'
import { EFFORT_TIERS, providerLabel } from '@/lib/models'
import { loadConversationsForUsage, computeUsageStats } from '@/lib/usageStats'
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
} from 'lucide-react'

interface SettingsModalProps {
  isOpen: boolean
  onClose: () => void
}

type TabType = 'general' | 'model' | 'prompt' | 'keys' | 'tools' | 'usage' | 'data'

const KEY_PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  google: 'Google',
  nvidia: 'NVIDIA',
  huggingface: 'Hugging Face',
}

const TIER_STYLES: Record<string, string> = {
  low: 'bg-gray-400/15 text-gray-500 dark:text-gray-400',
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
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({})
  const [revealedKeys, setRevealedKeys] = useState<Record<string, boolean>>({})
  const [keyBusy, setKeyBusy] = useState<string | null>(null)
  const [keySaveError, setKeySaveError] = useState<string | null>(null)
  const [keyPromptModel, setKeyPromptModel] = useState<ModelInfo | null>(null)

  const { keys: providerKeys, isLoading: keysLoading, error: keysError, reload: reloadKeys } =
    useProviderKeys(isOpen && activeTab === 'keys')

  const { servers: mcpServers, isLoading: mcpLoading, error: mcpError, reload: reloadMcp } =
    useMcpStatus(isOpen && activeTab === 'tools')

  const usageStats = useMemo(
    () => (activeTab === 'usage' ? computeUsageStats(loadConversationsForUsage()) : null),
    [activeTab]
  )

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

  const handleExportAll = () => {
    const raw = localStorage.getItem('dabba-conversations')
    if (!raw) {
      alert('No conversation history found to export.')
      return
    }
    const blob = new Blob([raw], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `dabba-conversations-export-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleClearHistory = () => {
    if (confirm('Are you sure you want to delete all conversation history? This action cannot be undone.')) {
      localStorage.removeItem('dabba-conversations')
      window.location.reload()
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
      className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-semibold transition-all ${
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in">
      <div
        className="fixed inset-0"
        onClick={onClose}
      />

      {/* Claude-style 2-Column Dialog Panel */}
      <div className="bg-surface dark:bg-surface-dark-secondary max-w-3xl w-full h-[640px] rounded-2xl overflow-hidden relative z-10 border border-border dark:border-border-dark shadow-xl m-4 flex">

        {/* Left Column: Navigation Sidebar */}
        <div className="w-[200px] border-r border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary p-4 flex flex-col justify-between">
          <div className="space-y-6">
            <div className="flex items-center gap-2 px-2 py-1">
              <SettingsIcon className="w-5 h-5 text-accent" />
              <span className="font-semibold text-sm tracking-tight text-text-primary dark:text-text-dark-primary">
                Dabba Settings
              </span>
            </div>

            <nav className="space-y-1">
              {navItem('general', <Globe className="w-4 h-4" />, 'General')}
              {navItem('model', <Sliders className="w-4 h-4" />, 'Model & Params')}
              {navItem('prompt', <MessageSquareCode className="w-4 h-4" />, 'System Prompts')}
              {navItem('keys', <KeyRound className="w-4 h-4" />, 'API Keys')}
              {navItem('tools', <Plug className="w-4 h-4" />, 'Tools (MCP)')}
              {navItem('usage', <BarChart3 className="w-4 h-4" />, 'Usage')}
              {navItem('data', <Database className="w-4 h-4" />, 'Data Controls')}
            </nav>
          </div>

          <button
            onClick={handleReset}
            className="flex items-center justify-center gap-2 text-[11px] text-text-tertiary hover:text-text-secondary px-3 py-2.5 rounded-xl hover:bg-surface dark:hover:bg-surface-dark-tertiary transition-colors border border-transparent"
            title="Reset to factory defaults"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Reset Defaults
          </button>
        </div>

        {/* Right Column: Tab View Content */}
        <div className="flex-1 flex flex-col bg-surface dark:bg-surface-dark-secondary overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4.5 border-b border-border dark:border-border-dark">
            <h3 className="font-bold text-sm text-text-primary dark:text-text-dark-primary capitalize">
              {activeTab === 'model' ? 'Model & Parameters'
                : activeTab === 'prompt' ? 'System Instructions'
                : activeTab === 'keys' ? 'Provider API Keys'
                : activeTab === 'tools' ? 'MCP Servers & Tools'
                : activeTab === 'usage' ? 'Usage Statistics'
                : activeTab + ' settings'}
            </h3>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors"
            >
              <X className="w-4.5 h-4.5" />
            </button>
          </div>

          {/* Content Pane */}
          <div className="flex-1 overflow-y-auto scrollbar-thin p-6 space-y-6">

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

                <div className="space-y-4 pt-3 border-t border-border dark:border-border-dark">
                  <div className="space-y-1.5">
                    <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                      API Server Base URL
                    </label>
                    <input
                      type="text"
                      value={localSettings.baseUrl}
                      onChange={e => setLocalSettings(prev => ({ ...prev, baseUrl: e.target.value }))}
                      placeholder="e.g. http://localhost:8080"
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

                  <label className="flex items-center justify-between gap-3 pt-2">
                    <span className="text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">
                      Stream responses
                    </span>
                    <Toggle
                      checked={localSettings.streaming}
                      onChange={v => setLocalSettings(prev => ({ ...prev, streaming: v }))}
                    />
                  </label>
                  {localSettings.streaming && (
                    <div className="space-y-2">
                      <div className="flex justify-between items-center text-xs">
                        <span className="font-semibold text-text-secondary dark:text-text-dark-secondary">Typing speed</span>
                        <span className="font-bold text-accent">{localSettings.typingSpeed} ms/token</span>
                      </div>
                      <input
                        type="range" min="0" max="60" step="5"
                        value={localSettings.typingSpeed}
                        onChange={e => setLocalSettings(prev => ({ ...prev, typingSpeed: parseInt(e.target.value) }))}
                        className="w-full accent-accent bg-surface-tertiary dark:bg-surface-dark-tertiary h-1.5 rounded-lg cursor-pointer"
                      />
                    </div>
                  )}
                </div>
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
                        <span className="text-[9px] font-semibold uppercase tracking-wider text-accent/70 flex-shrink-0">Current</span>
                        <span className="text-xs font-medium text-accent truncate">{currentModel.name}</span>
                        <span className={`text-[8px] font-semibold px-1 py-0.5 rounded uppercase flex-shrink-0 ${TIER_STYLES[currentModel.tier] ?? TIER_STYLES.medium}`}>
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
                          <div className="px-3 py-1 text-[9px] font-semibold uppercase tracking-wider text-text-tertiary dark:text-text-dark-tertiary bg-surface-secondary dark:bg-surface-dark-tertiary">
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
                                <span className={`text-[8px] font-semibold px-1 py-0.5 rounded uppercase flex-shrink-0 ${TIER_STYLES[m.tier] ?? TIER_STYLES.medium}`}>
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
                  <p className="text-[10px] text-text-tertiary">
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

                  <Slider label="Max Completion Output" value={localSettings.maxTokens} min={256} max={8192} step={256} unit=" tokens"
                    onChange={v => setLocalSettings(prev => ({ ...prev, maxTokens: v }))}
                    marks={['Short (256)', 'Standard (2048)', 'Extended (8192)']} />

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
                  <label className="block text-[10px] font-semibold text-text-tertiary uppercase tracking-wider">
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
            {activeTab === 'keys' && (
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
                            'text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase',
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
                              title="Remove key"
                              className="p-2 rounded-lg hover:bg-red-500/10 text-text-tertiary hover:text-red-500 disabled:opacity-40 transition-colors flex-shrink-0"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {keySaveError && (
                  <p className="text-xs text-red-500">{keySaveError}</p>
                )}
              </div>
            )}

            {/* Tools (MCP) Tab */}
            {activeTab === 'tools' && (
              <div className="space-y-4 animate-fade-in">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-text-secondary dark:text-text-dark-secondary">
                    Servers configured in <code className="font-mono text-[11px]">mcp_servers.json</code> on the Dabba server.
                  </p>
                  <button
                    onClick={reloadMcp}
                    className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-tertiary transition-colors"
                    title="Refresh"
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
                          <span className="text-[10px] text-text-tertiary">{s.connected ? 'connected' : 'disconnected'}</span>
                        </div>
                        <p className="text-[10px] font-mono text-text-tertiary mt-1 truncate">{s.command} {s.args?.join(' ')}</p>
                        {s.tools?.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {s.tools.map(t => (
                              <span key={t} className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-surface dark:bg-surface-dark text-text-secondary dark:text-text-dark-secondary">
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

            {/* Usage Tab */}
            {activeTab === 'usage' && usageStats && (
              <div className="space-y-5 animate-fade-in">
                <div className="grid grid-cols-3 gap-3">
                  <StatCard label="Conversations" value={usageStats.totalConversations} />
                  <StatCard label="Messages" value={usageStats.totalMessages} />
                  <StatCard label="Total Tokens" value={usageStats.totalTokens.toLocaleString()} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <StatCard label="Prompt Tokens" value={usageStats.promptTokens.toLocaleString()} />
                  <StatCard label="Completion Tokens" value={usageStats.completionTokens.toLocaleString()} />
                </div>

                <div className="space-y-2 pt-2 border-t border-border dark:border-border-dark">
                  <label className="block text-[10px] font-semibold text-text-tertiary uppercase tracking-wider">
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
                              <span className="font-medium text-text-primary dark:text-text-dark-primary">{m.model}</span>
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
                <p className="text-[10px] text-text-tertiary">
                  Computed from conversations saved in this browser. Clearing history (Data Controls) resets these stats.
                </p>
              </div>
            )}

            {/* Data Controls Tab */}
            {activeTab === 'data' && (
              <div className="space-y-5 animate-fade-in">
                <div className="p-4 rounded-2xl bg-surface-secondary dark:bg-surface-dark-tertiary border border-border dark:border-border-dark space-y-2">
                  <h4 className="text-xs font-bold text-text-primary dark:text-text-dark-primary flex items-center gap-1.5">
                    <Download className="w-4 h-4 text-accent" />
                    Export Local Data
                  </h4>
                  <p className="text-xs text-text-secondary dark:text-text-dark-secondary leading-relaxed">
                    Download all your saved conversation records as a single structured JSON file. You can import this data back into the app or backup your sessions.
                  </p>
                  <button
                    onClick={handleExportAll}
                    className="flex items-center gap-2 mt-2 px-4 py-2.5 rounded-xl text-xs font-semibold bg-surface dark:bg-surface-dark-tertiary hover:bg-accent/10 border border-border dark:border-border-dark hover:border-accent/30 text-text-primary dark:text-text-dark-primary transition-colors"
                  >
                    <Download className="w-4 h-4" />
                    Export Conversations (.json)
                  </button>
                </div>

                <div className="p-4 rounded-2xl bg-red-500/5 dark:bg-red-500/10 border border-red-500/10 dark:border-red-500/20 space-y-2">
                  <h4 className="text-xs font-bold text-red-500 flex items-center gap-1.5">
                    <Trash2 className="w-4 h-4" />
                    Danger Zone
                  </h4>
                  <p className="text-xs text-text-secondary dark:text-text-dark-secondary leading-relaxed">
                    Permanently delete all conversation records stored in your browser session. This will clear the chat history list and resets the current window.
                  </p>
                  <button
                    onClick={handleClearHistory}
                    className="flex items-center gap-2 mt-2 px-4 py-2.5 rounded-xl text-xs font-semibold bg-red-500/10 hover:bg-red-500/25 border border-red-500/25 text-red-500 hover:text-white transition-all active:scale-[0.98]"
                  >
                    <Trash2 className="w-4 h-4" />
                    Clear History & Reset
                  </button>
                </div>
              </div>
            )}

          </div>

          {/* Footer Controls */}
          <div className="px-6 py-4 border-t border-border dark:border-border-dark flex items-center justify-end gap-2 bg-surface-secondary dark:bg-surface-dark-tertiary">
            {isSavedAlert ? (
              <span className="text-xs text-green-500 font-bold flex items-center gap-1 animate-fade-in mr-auto">
                <Check className="w-4 h-4" />
                Settings Saved!
              </span>
            ) : null}

            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="px-5 py-2.5 rounded-xl text-xs font-bold bg-accent hover:bg-accent-hover text-white transition-colors"
            >
              Save Settings
            </button>
          </div>
        </div>

      </div>

      {keyPromptModel && (
        <ApiKeyPromptModal
          provider={keyPromptModel.provider}
          modelName={keyPromptModel.name}
          onClose={() => setKeyPromptModel(null)}
          onSaved={() => {
            setLocalSettings(prev => ({ ...prev, model: keyPromptModel.id }))
            reloadModels()
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
        <span className="font-bold text-accent">{value}{unit}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full accent-accent bg-surface-tertiary dark:bg-surface-dark-tertiary h-1.5 rounded-lg cursor-pointer"
      />
      <div className="flex justify-between text-[10px] text-text-tertiary">
        {marks.map(m => <span key={m}>{m}</span>)}
      </div>
    </div>
  )
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`relative w-9 h-5 rounded-full transition-colors flex-shrink-0 ${checked ? 'bg-accent' : 'bg-surface-tertiary dark:bg-surface-dark-tertiary'}`}
    >
      <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : ''}`} />
    </button>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="p-3 rounded-xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary">
      <div className="text-lg font-bold text-text-primary dark:text-text-dark-primary">{value}</div>
      <div className="text-[10px] text-text-tertiary uppercase tracking-wide">{label}</div>
    </div>
  )
}
