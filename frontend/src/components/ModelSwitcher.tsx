import { useState, useRef, useEffect, useMemo } from 'react'
import { ChevronDown, Check, Search, Zap, KeyRound, RefreshCw, Loader2 } from 'lucide-react'
import { useSettings } from '@/hooks/useSettings'
import { useModels } from '@/hooks/useModels'
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

export function ModelSwitcher() {
  const { settings, updateSettings } = useSettings()
  const { models, isLoading, error, reload } = useModels()
  const [openMenu, setOpenMenu] = useState<'model' | 'effort' | null>(null)
  const [search, setSearch] = useState('')
  const [keyPromptModel, setKeyPromptModel] = useState<ModelInfo | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpenMenu(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    if (openMenu === 'model') {
      setSearch('')
      setTimeout(() => searchRef.current?.focus(), 20)
    }
  }, [openMenu])

  const current = models.find(m => m.id === settings.model)

  // Group filtered models by provider, preserving catalog order.
  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = q
      ? models.filter(m =>
          m.name.toLowerCase().includes(q) ||
          m.id.toLowerCase().includes(q) ||
          m.provider.toLowerCase().includes(q)
        )
      : models
    const groups: { provider: string; items: ModelInfo[] }[] = []
    for (const m of filtered) {
      let g = groups.find(x => x.provider === m.provider)
      if (!g) { g = { provider: m.provider, items: [] }; groups.push(g) }
      g.items.push(m)
    }
    return groups
  }, [models, search])

  const selectModel = (m: ModelInfo) => {
    if (!m.has_key) {
      setKeyPromptModel(m)
      setOpenMenu(null)
      return
    }
    updateSettings({ model: m.id })
    setOpenMenu(null)
  }

  const currentEffort = EFFORT_TIERS.find(t => t.id === settings.effort) ?? EFFORT_TIERS[1]

  return (
    <div className="relative flex items-center gap-1.5" ref={ref}>
      {/* Model chip */}
      <button
        onClick={() => setOpenMenu(openMenu === 'model' ? null : 'model')}
        className="flex items-center gap-1.5 px-2 py-1 -ml-2 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
        title="Switch model"
      >
        <span className="text-[10px] font-medium text-text-secondary dark:text-text-dark-secondary truncate max-w-[180px]">
          {current?.name ?? settings.model}
        </span>
        {current && (
          <span className={cn('text-[8px] font-semibold px-1 py-0.5 rounded uppercase', TIER_STYLES[current.tier] ?? TIER_STYLES.medium)}>
            {current.tier}
          </span>
        )}
        <ChevronDown className="w-3 h-3 text-text-tertiary dark:text-text-dark-tertiary" />
      </button>

      {/* Effort chip */}
      <button
        onClick={() => setOpenMenu(openMenu === 'effort' ? null : 'effort')}
        className="flex items-center gap-1 px-2 py-1 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
        title="Reasoning effort"
      >
        <Zap className="w-3 h-3 text-accent" />
        <span className="text-[10px] font-medium text-text-secondary dark:text-text-dark-secondary">
          {currentEffort.label}
        </span>
        <ChevronDown className="w-3 h-3 text-text-tertiary dark:text-text-dark-tertiary" />
      </button>

      {/* Model dropdown */}
      {openMenu === 'model' && (
        <div className="absolute left-0 top-full mt-1.5 w-80 max-h-[420px] flex flex-col rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-40 animate-fade-in overflow-hidden">
          <div className="p-2 border-b border-border dark:border-border-dark">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-tertiary" />
              <input
                ref={searchRef}
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search models…"
                className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg glass-input outline-none focus:border-accent/50 transition-colors"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin py-1">
            {isLoading && models.length === 0 ? (
              <div className="flex items-center justify-center gap-2 py-6 text-xs text-text-tertiary">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading models…
              </div>
            ) : grouped.length === 0 ? (
              <div className="py-6 text-center text-xs text-text-tertiary">No models match “{search}”.</div>
            ) : (
              grouped.map(group => (
                <div key={group.provider} className="mb-1">
                  <div className="px-3 py-1 text-[9px] font-semibold uppercase tracking-wider text-text-tertiary dark:text-text-dark-tertiary">
                    {providerLabel(group.provider)}
                  </div>
                  {group.items.map(model => {
                    const active = model.id === settings.model
                    return (
                      <button
                        key={model.id}
                        onClick={() => selectModel(model)}
                        className={cn(
                          'w-full flex items-start gap-2 px-3 py-1.5 text-left transition-colors',
                          !model.has_key
                            ? 'opacity-80 hover:opacity-100 hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
                            : active
                              ? 'bg-accent/10'
                              : 'hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
                        )}
                        title={model.has_key ? model.description : `Click to add a ${providerLabel(model.provider)} API key`}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className={cn(
                              'text-xs font-medium truncate',
                              active ? 'text-accent' : 'text-text-primary dark:text-text-dark-primary'
                            )}>
                              {model.name}
                            </span>
                            <span className={cn('text-[8px] font-semibold px-1 py-0.5 rounded uppercase flex-shrink-0', TIER_STYLES[model.tier] ?? TIER_STYLES.medium)}>
                              {model.tier}
                            </span>
                            {!model.has_key && <KeyRound className="w-2.5 h-2.5 text-text-tertiary flex-shrink-0" />}
                          </div>
                          <p className="text-[10px] text-text-tertiary dark:text-text-dark-tertiary truncate">
                            {model.description}
                          </p>
                        </div>
                        {active && <Check className="w-3.5 h-3.5 text-accent flex-shrink-0 mt-0.5" />}
                      </button>
                    )
                  })}
                </div>
              ))
            )}
          </div>

          {error && (
            <div className="px-3 py-2 border-t border-border dark:border-border-dark flex items-center justify-between gap-2">
              <span className="text-[10px] text-amber-600 dark:text-amber-400 truncate">Using fallback list — server unreachable</span>
              <button onClick={reload} className="p-1 rounded hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-tertiary" title="Retry">
                <RefreshCw className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>
      )}

      {/* Effort dropdown */}
      {openMenu === 'effort' && (
        <div className="absolute left-0 top-full mt-1.5 w-56 rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-40 py-1 animate-fade-in">
          {EFFORT_TIERS.map(tier => (
            <button
              key={tier.id}
              onClick={() => { updateSettings({ effort: tier.id }); setOpenMenu(null) }}
              className={cn(
                'w-full flex items-center justify-between gap-2 px-3 py-2 text-left transition-colors',
                tier.id === settings.effort
                  ? 'bg-accent/10'
                  : 'hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
              )}
            >
              <div>
                <div className={cn('text-xs font-medium', tier.id === settings.effort ? 'text-accent' : 'text-text-primary dark:text-text-dark-primary')}>
                  {tier.label}
                </div>
                <div className="text-[10px] text-text-tertiary dark:text-text-dark-tertiary">{tier.hint}</div>
              </div>
              {tier.id === settings.effort && <Check className="w-3.5 h-3.5 text-accent flex-shrink-0" />}
            </button>
          ))}
        </div>
      )}

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
