import { useDialogFocus } from '@/hooks/useDialogFocus'
import { useState, useRef, useEffect, useMemo } from 'react'
import { ChevronDown, Check, Search, KeyRound, RefreshCw, Loader2 } from 'lucide-react'
import { useSettings } from '@/hooks/useSettings'
import { useModels } from '@/hooks/useModels'
import { EFFORT_TIERS, providerLabel, rememberModelNames, modelDisplayName, formatContextWindow } from '@/lib/models'
import { ApiKeyPromptModal } from './ApiKeyPromptModal'
import { TierStack } from './TierStack'
import type { ModelInfo } from '@/types'
import { cn } from '@/lib/utils'

export function ModelSwitcher({ placement = 'down' }: { placement?: 'down' | 'up' } = {}) {
  const { settings, updateSettings } = useSettings()
  const { models, isLoading, error, reload } = useModels()
  const [openMenu, setOpenMenu] = useState<'model' | 'effort' | null>(null)
  const [search, setSearch] = useState('')
  const [keyPromptModel, setKeyPromptModel] = useState<ModelInfo | null>(null)
  // Which side the open menu uses and how tall it may be, measured when it opens.
  const [fit, setFit] = useState<{ side: 'up' | 'down'; maxHeight: number }>({ side: placement, maxHeight: 420 })
  const ref = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const modelMenuRef = useDialogFocus(openMenu === 'model', () => setOpenMenu(null))
  const effortMenuRef = useDialogFocus(openMenu === 'effort', () => setOpenMenu(null))

  // Open on the preferred side, but never let the menu run off the page: it
  // is capped to the room available, and flips to the other side when that
  // side has clearly more space (e.g. a composer near the top of a short window).
  const measureFit = () => {
    const rect = ref.current?.getBoundingClientRect()
    if (!rect) return
    const HEADER = 72 // keep clear of the page header
    const above = rect.top - HEADER
    const below = window.innerHeight - rect.bottom - 16
    const preferUp = placement === 'up'
    const preferred = preferUp ? above : below
    const other = preferUp ? below : above
    const flip = preferred < 260 && other > preferred
    const side: 'up' | 'down' = flip ? (preferUp ? 'down' : 'up') : placement
    const room = side === 'up' ? above : below
    setFit({ side, maxHeight: Math.max(160, Math.min(420, Math.floor(room) - 8)) })
  }
  const toggleMenu = (menu: 'model' | 'effort') => {
    if (openMenu !== menu) measureFit()
    setOpenMenu(openMenu === menu ? null : menu)
  }

  // Phones keep the bottom sheet style for 'up' menus; from md up the menu is
  // anchored to the chips on the measured side.
  const menuPosition = cn(
    placement === 'up' && 'max-md:fixed max-md:bottom-4 max-md:right-4 max-md:max-w-[calc(100%-2rem)]',
    placement === 'up'
      ? (fit.side === 'up' ? 'md:bottom-full md:right-0 md:mb-2' : 'md:top-full md:right-0 md:mt-2')
      : (fit.side === 'down' ? 'left-0 top-full mt-2' : 'left-0 bottom-full mb-2'),
  )
  const menuStyle = { '--menu-max-h': `${fit.maxHeight}px` } as React.CSSProperties

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpenMenu(null)
      }
    }
    // U7: a menu left open over the chat must not linger while the page
    // scrolls beneath it; scrolling inside the menu itself is ignored.
    function handleScroll(e: Event) {
      if (ref.current && e.target instanceof Node && ref.current.contains(e.target)) return
      setOpenMenu(null)
    }
    document.addEventListener('scroll', handleScroll, true)
    document.addEventListener('mousedown', handleClickOutside)
    return () => { document.removeEventListener('scroll', handleScroll, true); document.removeEventListener('mousedown', handleClickOutside) }
  }, [])

  useEffect(() => {
    if (openMenu === 'model') {
      setSearch('')
      setTimeout(() => searchRef.current?.focus(), 20)
    }
  }, [openMenu])

  useEffect(() => { rememberModelNames(models) }, [models])
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
    // U3: the active model is pinned in a "Current" section at the top, and
    // models that still need an API key are grouped last, so the list starts
    // with what you're using and what's ready to use.
    const groups: { provider: string; label: string; items: ModelInfo[] }[] = []
    const active = filtered.find(m => m.id === settings.model)
    if (active) groups.push({ provider: '__current', label: 'Current', items: [active] })
    const needsKey: ModelInfo[] = []
    for (const m of filtered) {
      if (m === active) continue
      if (!m.has_key) { needsKey.push(m); continue }
      let g = groups.find(x => x.provider === m.provider)
      if (!g) { g = { provider: m.provider, label: providerLabel(m.provider), items: [] }; groups.push(g) }
      g.items.push(m)
    }
    if (needsKey.length) groups.push({ provider: '__needs_key', label: 'Needs API key', items: needsKey })
    return groups
  }, [models, search, settings.model])

  // Arrow keys move between model options (and from the search box into the
  // list); Enter/Space activate the focused option as a normal button.
  const handleListKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    const options = Array.from(modelMenuRef.current?.querySelectorAll<HTMLElement>('[data-model-option]') ?? [])
    if (!options.length) return
    e.preventDefault()
    const at = options.indexOf(document.activeElement as HTMLElement)
    const next = e.key === 'ArrowDown'
      ? options[at === -1 ? 0 : Math.min(at + 1, options.length - 1)]
      : at <= 0 ? searchRef.current ?? options[0] : options[at - 1]
    next.focus()
  }

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
    <div className="relative flex min-w-0 items-center gap-0.5 lg:gap-1.5" ref={ref}>
      {/* Model chip */}
      <button
        onClick={() => toggleMenu('model')}
        className={cn(
          'flex min-w-0 items-center gap-1 h-9 px-1 lg:h-8 lg:gap-2 lg:px-2 rounded-lg text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors',
          placement === 'down' && '-ml-2'
        )}
        aria-expanded={openMenu === 'model'}
        aria-haspopup="dialog"
        aria-label={`Model: ${current?.name ?? modelDisplayName(settings.model)}. Change model`}
        title="Switch model"
      >
        <span className="text-[13px] font-medium text-text-primary dark:text-text-dark-primary min-w-0 truncate max-w-[200px]">
          {current?.name ?? modelDisplayName(settings.model)}
        </span>
        {current && <TierStack tier={current.tier} className="hidden lg:inline-flex" />}
        <ChevronDown className="w-4 h-4 shrink-0 text-text-tertiary dark:text-text-dark-tertiary" strokeWidth={1.5} />
      </button>

      {/* Effort chip */}
      <button
        onClick={() => toggleMenu('effort')}
        className="flex shrink-0 items-center gap-1 h-9 px-2 lg:h-8 lg:gap-2 rounded-lg text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
        aria-expanded={openMenu === 'effort'}
        aria-haspopup="dialog"
        aria-label={`Reasoning effort: ${currentEffort.label}. Change effort`}
        title="Reasoning effort"
      >
        <TierStack tier={currentEffort.id} />
        <span className="hidden whitespace-nowrap text-[13px] lg:inline">
          {currentEffort.label} effort
        </span>
        <ChevronDown className="w-4 h-4 shrink-0 text-text-tertiary dark:text-text-dark-tertiary" strokeWidth={1.5} />
      </button>

      {/* Model dropdown */}
      {openMenu === 'model' && (
        <div ref={modelMenuRef} role="dialog" aria-label="Choose model" tabIndex={-1} onKeyDown={handleListKeyDown} style={menuStyle} className={cn('absolute w-80 max-md:max-h-[min(420px,calc(100dvh-2rem))] md:max-h-[var(--menu-max-h)] flex flex-col rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-40 animate-fade-in overflow-hidden', menuPosition)}>
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
                    {group.label}
                  </div>
                  {group.items.map(model => {
                    const active = model.id === settings.model
                    return (
                      <button
                        key={model.id}
                        data-model-option
                        aria-current={active ? 'true' : undefined}
                        aria-label={`${model.name}${active ? ' (current)' : ''}${model.has_key ? '' : ' (needs API key)'}`}
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
                          <p className="text-xs text-text-tertiary dark:text-text-dark-tertiary">
                            {[
                              formatContextWindow(model.contextWindow),
                              model.supportsVision && 'Vision',
                              model.supportsThinking && 'Reasoning',
                              model.keySource && `Key: ${model.keySource}`,
                            ].filter(Boolean).join(' · ')}
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
        <div ref={effortMenuRef} role="dialog" aria-label="Reasoning effort" tabIndex={-1} style={menuStyle} className={cn('absolute w-60 max-md:max-h-[calc(100dvh-2rem)] md:max-h-[var(--menu-max-h)] overflow-y-auto rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-40 py-1 animate-fade-in', menuPosition)}>
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
