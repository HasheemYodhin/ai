import { useState, useMemo } from 'react'
import { Bot, Search, Check, KeyRound, Loader2, Zap } from 'lucide-react'
import { useModels } from '@/hooks/useModels'
import { useSettings } from '@/hooks/useSettings'
import { EFFORT_TIERS, providerLabel } from '@/lib/models'
import { ApiKeyPromptModal } from './ApiKeyPromptModal'
import type { ModelInfo } from '@/types'
import { cn } from '@/lib/utils'

const TIER_STYLES: Record<string, string> = {
  low: 'bg-gray-400/15 text-gray-500 dark:text-gray-400',
  medium: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
  high: 'bg-violet-500/15 text-violet-600 dark:text-violet-400',
  xhigh: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  max: 'bg-accent/15 text-accent',
}

/** Full-page browser over the live model catalog — "Agents" in the sidebar nav. */
export function AgentsPage() {
  const { models, isLoading, reload } = useModels()
  const { settings, updateSettings } = useSettings()
  const [search, setSearch] = useState('')
  const [keyPromptModel, setKeyPromptModel] = useState<ModelInfo | null>(null)

  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = q
      ? models.filter(m => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q) || m.provider.toLowerCase().includes(q))
      : models
    const groups: Record<string, typeof models> = {}
    for (const m of filtered) (groups[m.provider] ??= []).push(m)
    return groups
  }, [models, search])

  return (
    <div className="flex flex-col h-full overflow-y-auto scrollbar-thin">
      <header className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border-dark">
        <h1 className="text-sm font-bold text-text-primary dark:text-text-dark-primary flex items-center gap-2">
          <Bot className="w-4 h-4 text-accent" /> Agents
        </h1>
        <div className="flex items-center gap-1.5">
          <Zap className="w-3.5 h-3.5 text-accent" />
          <select
            value={settings.effort}
            onChange={e => updateSettings({ effort: e.target.value })}
            className="text-xs rounded-lg glass-input border border-border dark:border-border-dark px-2 py-1 outline-none"
          >
            {EFFORT_TIERS.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </div>
      </header>

      <div className="px-6 py-4">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-tertiary" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search agents…"
            className="w-full pl-8 pr-3 py-2 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
          />
        </div>
      </div>

      <div className="flex-1 px-6 pb-6">
        {isLoading && models.length === 0 ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-text-tertiary">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading agents…
          </div>
        ) : (
          Object.entries(grouped).map(([provider, items]) => (
            <div key={provider} className="mb-6">
              <h4 className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary mb-2">{providerLabel(provider)}</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {items.map(m => {
                  const active = m.id === settings.model
                  return (
                    <button
                      key={m.id}
                      onClick={() => m.has_key ? updateSettings({ model: m.id }) : setKeyPromptModel(m)}
                      title={m.has_key ? m.description : `Click to add a ${providerLabel(m.provider)} API key`}
                      className={cn(
                        'flex items-start gap-3 p-3 rounded-xl border text-left transition-colors',
                        !m.has_key
                          ? 'border-dashed border-border dark:border-border-dark hover:border-accent/30 opacity-80 hover:opacity-100'
                          : active
                            ? 'border-accent/40 bg-accent/5'
                            : 'border-border dark:border-border-dark hover:border-accent/30 bg-surface-secondary dark:bg-surface-dark-tertiary'
                      )}
                    >
                      <div className="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center flex-shrink-0">
                        <Bot className="w-4 h-4 text-accent" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm font-medium text-text-primary dark:text-text-dark-primary truncate">{m.name}</span>
                          <span className={cn('text-[8px] font-semibold px-1 py-0.5 rounded uppercase flex-shrink-0', TIER_STYLES[m.tier] ?? TIER_STYLES.medium)}>{m.tier}</span>
                        </div>
                        <p className="text-xs text-text-tertiary dark:text-text-dark-tertiary truncate">
                          {m.has_key ? m.description : 'Click to add API key'}
                        </p>
                      </div>
                      {active ? (
                        <Check className="w-4 h-4 text-accent flex-shrink-0" />
                      ) : !m.has_key ? (
                        <KeyRound className="w-3.5 h-3.5 text-text-tertiary flex-shrink-0" />
                      ) : null}
                    </button>
                  )
                })}
              </div>
            </div>
          ))
        )}
      </div>

      {keyPromptModel && (
        <ApiKeyPromptModal
          provider={keyPromptModel.provider}
          modelName={keyPromptModel.name}
          onClose={() => setKeyPromptModel(null)}
          onSaved={() => {
            updateSettings({ model: keyPromptModel.id })
            reload()
          }}
        />
      )}
    </div>
  )
}
