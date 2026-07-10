import { useState, useRef, useEffect } from 'react'
import { RefreshCw, Check, Loader2 } from 'lucide-react'
import { useModels } from '@/hooks/useModels'
import { useSettings } from '@/hooks/useSettings'
import { providerLabel } from '@/lib/models'
import { cn } from '@/lib/utils'

interface RegenerateMenuProps {
  onRegenerate: (overrides?: { model?: string; effort?: string }) => void
}

/**
 * Regenerate button with a dropdown to re-run the reply on a *different* model.
 * useModels only fires when the menu is actually opened (component stays cheap
 * until then), so we don't fetch the catalog for every message bubble.
 */
export function RegenerateMenu({ onRegenerate }: RegenerateMenuProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => onRegenerate()}
        onContextMenu={(e) => { e.preventDefault(); setOpen(o => !o) }}
        title="Regenerate (right-click for model options)"
        className="p-1 rounded-md text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
      >
        <RefreshCw className="w-3 h-3" />
      </button>
      <button
        onClick={() => setOpen(o => !o)}
        title="Regenerate with a different model"
        className="px-0.5 rounded-md text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors text-[9px]"
      >
        ▾
      </button>
      {open && <ModelMenu onPick={(model) => { setOpen(false); onRegenerate({ model }) }} />}
    </div>
  )
}

function ModelMenu({ onPick }: { onPick: (model: string) => void }) {
  const { models, isLoading } = useModels()
  const { settings } = useSettings()

  return (
    <div className="absolute right-0 top-full mt-1 w-64 max-h-72 overflow-y-auto scrollbar-thin rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-40 py-1 animate-fade-in">
      <div className="px-3 py-1 text-[9px] font-semibold uppercase tracking-wider text-text-tertiary">
        Regenerate with
      </div>
      {isLoading && models.length === 0 ? (
        <div className="flex items-center gap-2 px-3 py-3 text-xs text-text-tertiary">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
        </div>
      ) : (
        models.filter(m => m.has_key).map(m => (
          <button
            key={m.id}
            onClick={() => onPick(m.id)}
            className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-left hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
          >
            <span className="min-w-0">
              <span className="block text-xs font-medium text-text-primary dark:text-text-dark-primary truncate">{m.name}</span>
              <span className="block text-[9px] text-text-tertiary">{providerLabel(m.provider)}</span>
            </span>
            {m.id === settings.model && <Check className={cn('w-3.5 h-3.5 text-accent flex-shrink-0')} />}
          </button>
        ))
      )}
    </div>
  )
}
