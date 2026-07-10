import { useState, useEffect } from 'react'
import { X, Check, Folder } from 'lucide-react'
import { PROJECT_COLORS, type ProjectInput } from '@/hooks/useProjects'
import type { Project } from '@/types'
import { cn } from '@/lib/utils'

interface ProjectModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (input: ProjectInput) => void
  /** When set, the modal edits this project instead of creating a new one. */
  initial?: Project | null
}

export function ProjectModal({ isOpen, onClose, onSubmit, initial }: ProjectModalProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [instructions, setInstructions] = useState('')
  const [color, setColor] = useState(PROJECT_COLORS[0])

  useEffect(() => {
    if (isOpen) {
      setName(initial?.name ?? '')
      setDescription(initial?.description ?? '')
      setInstructions(initial?.instructions ?? '')
      setColor(initial?.color ?? PROJECT_COLORS[0])
    }
  }, [isOpen, initial])

  if (!isOpen) return null

  const handleSubmit = () => {
    if (!name.trim()) return
    onSubmit({ name, description, instructions, color })
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in">
      <div className="fixed inset-0" onClick={onClose} />

      <div className="bg-surface dark:bg-surface-dark-secondary max-w-md w-full rounded-2xl overflow-hidden relative z-10 border border-border dark:border-border-dark shadow-xl m-4">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border dark:border-border-dark">
          <h3 className="flex items-center gap-2 font-bold text-sm text-text-primary dark:text-text-dark-primary">
            <Folder className="w-4 h-4 text-accent" />
            {initial ? 'Edit project' : 'New project'}
          </h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Name</label>
            <input
              autoFocus
              value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSubmit()}
              placeholder="e.g. Marketing site redesign"
              className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Description <span className="text-text-tertiary font-normal">(optional)</span></label>
            <input
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Shown in the sidebar"
              className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Instructions <span className="text-text-tertiary font-normal">(optional)</span></label>
            <textarea
              value={instructions}
              onChange={e => setInstructions(e.target.value)}
              placeholder="Applied automatically as the system prompt for every conversation in this project…"
              rows={4}
              className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 resize-none scrollbar-thin leading-relaxed"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Color</label>
            <div className="flex items-center gap-2">
              {PROJECT_COLORS.map(c => (
                <button
                  key={c}
                  onClick={() => setColor(c)}
                  className={cn(
                    'w-7 h-7 rounded-full flex items-center justify-center transition-transform',
                    color === c && 'ring-2 ring-offset-2 ring-offset-surface dark:ring-offset-surface-dark-secondary scale-105'
                  )}
                  style={{ background: c, ...(color === c ? { '--tw-ring-color': c } as React.CSSProperties : {}) }}
                >
                  {color === c && <Check className="w-3.5 h-3.5 text-white" />}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="px-5 py-4 border-t border-border dark:border-border-dark flex items-center justify-end gap-2 bg-surface-secondary dark:bg-surface-dark-tertiary">
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-xs font-semibold hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!name.trim()}
            className="px-5 py-2.5 rounded-xl text-xs font-bold bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors"
          >
            {initial ? 'Save changes' : 'Create project'}
          </button>
        </div>
      </div>
    </div>
  )
}
