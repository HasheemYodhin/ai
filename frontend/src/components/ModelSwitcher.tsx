import { useState, useRef, useEffect, useMemo } from 'react'
import { ChevronDown, Check, Search, KeyRound, RefreshCw, Loader2 } from 'lucide-react'
import { useSettings } from '@/hooks/useSettings'
import { useModels } from '@/hooks/useModels'
import { EFFORT_TIERS, providerLabel } from '@/lib/models'
import { ApiKeyPromptModal } from './ApiKeyPromptModal'
import { TierStack } from './TierStack'
import type { ModelInfo } from '@/types'
import { cn } from '@/lib/utils'

export function ModelSwitcher({ placement = 'down' }: { placement?: 'down' | 'up' } = {}) {
  const menuPosition = placement === 'up' ? 'right-0 bottom-full mb-2' : 'left-0 top-full mt-2'
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
        className={cn(
          'flex items-center gap-2 h-8 px-2 rounded-lg text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors',
          placement === 'down' && '-ml-2'
        )}
        title="Switch model"
      >
        <span className="text-[13px] font-medium text-text-primary dark:text-text-dark-primary truncate max-w-[200px]">
          {current?.name ?? settings.model}
        </span>
        {current && <TierStack tier={current.tier} />}
        <ChevronDown className="w-4 h-4 text-text-tertiary dark:text-text-dark-tertiary" strokeWidth={1.5} />
      </button>

      {/* Effort chip */}
      <button
        onClick={() => setOpenMenu(openMenu === 'effort' ? null : 'effort')}
        className="flex items-center gap-2 h-8 px-2 rounded-lg text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
        title="Reasoning effort"
      >
        <TierStack tier={currentEffort.id} />
        <span className="text-[13px]">
          {currentEffort.label} effort
        </span>
        <ChevronDown className="w-4 h-4 text-text-tertiary dark:text-text-dark-tertiary" strokeWidth={1.5} />
      </button>

      {/* Model dropdown */}
      {openMenu === 'model' && (
        <div className={cn('absolute w-80 max-h-[420px] flex flex-col rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-40 animate-fade-in overflow-hidden', menuPosition)}>
          <div className="p-2 border-b border-border dark:border-border-dark">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" strokeWidth={1.5} />
              <input
                ref={searchRef}
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search models"
                className="w-full h-8 pl-8 pr-3 text-[13px] rounded-lg glass-input outline-none focus:border-accent/50 transition-colors"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin py-1">
            {isLoading && models.length === 0 ? (
              <div className="flex items-center justify-center gap-2 py-6 text-[13px] text-text-tertiary">
                <Loader2 className="w-4 h-4 animate-spin" strokeWidth={1.5} /> Loading models
              </div>
            ) : grouped.length === 0 ? (
              <div className="py-6 text-center text-[13px] text-text-tertiary">No models match “{search}”</div>
            ) : (
              grouped.map(group => (
                <div key={group.provider} className="mb-2">
                  <div className="px-3 pt-2 pb-1 text-xs text-text-tertiary dark:text-text-dark-tertiary">
                    {providerLabel(group.provider)}
                  </div>
                  {group.items.map(model => {
                    const active = model.id === settings.model
                    return (
                      <button
                        key={model.id}
                        onClick={() => selectModel(model)}
                        className={cn(
                          'w-full flex items-start gap-2 px-3 py-2 text-left transition-colors',
                          !model.has_key
                            ? 'opacity-80 hover:opacity-100 hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
                            : active
                              ? 'bg-accent/10'
                              : 'hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
                        )}
                        title={model.has_key ? model.description : `Click to add a ${providerLabel(model.provider)} API key`}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className={cn(
                              'text-[13px] font-medium truncate',
                              active ? 'text-accent' : 'text-text-primary dark:text-text-dark-primary'
                            )}>
                              {model.name}
                            </span>
                            <TierStack tier={model.tier} className="text-text-tertiary dark:text-text-dark-tertiary" />
                            {!model.has_key && <KeyRound className="w-3 h-3 text-text-tertiary flex-shrink-0" strokeWidth={1.5} />}
                          </div>
                          <p className="text-xs text-text-tertiary dark:text-text-dark-tertiary truncate">
                            {model.description}
                          </p>
                        </div>
                        {active && <Check className="w-4 h-4 text-accent flex-shrink-0 mt-0.5" strokeWidth={1.5} />}
                      </button>
                    )
                  })}
                </div>
              ))
            )}
          </div>

          {error && (
            <div className="px-3 py-2 border-t border-border dark:border-border-dark flex items-center justify-between gap-2">
              <span className="text-xs text-amber-700 dark:text-amber-400 truncate">Server unreachable, showing saved list</span>
              <button onClick={reload} className="p-1 rounded-md hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-tertiary transition-colors" title="Retry">
                <RefreshCw className="w-4 h-4" strokeWidth={1.5} />
              </button>
            </div>
          )}
        </div>
      )}

      {/* Effort dropdown */}
      {openMenu === 'effort' && (
        <div className={cn('absolute w-60 rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-40 py-1 animate-fade-in', menuPosition)}>
          {EFFORT_TIERS.map(tier => (
            <button
              key={tier.id}
              onClick={() => { updateSettings({ effort: tier.id }); setOpenMenu(null) }}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2 text-left transition-colors',
                tier.id === settings.effort
                  ? 'bg-accent/10 text-accent'
                  : 'text-text-tertiary dark:text-text-dark-tertiary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
              )}
            >
              <TierStack tier={tier.id} />
              <div className="flex-1">
                <div className={cn('text-[13px] font-medium', tier.id === settings.effort ? 'text-accent' : 'text-text-primary dark:text-text-dark-primary')}>
                  {tier.label}
                </div>
                <div className="text-xs text-text-tertiary dark:text-text-dark-tertiary">{tier.hint}</div>
              </div>
              {tier.id === settings.effort && <Check className="w-4 h-4 text-accent flex-shrink-0" strokeWidth={1.5} />}
            </button>
          ))}
        </div>
      )}

      {keyPromptModel && (
        <ApiKeyPromptModal
          target={keyPromptModel.id}
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
