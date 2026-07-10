import { useState, useEffect } from 'react'
import { X, Sparkles } from 'lucide-react'
import type { SkillInput } from '@/hooks/useSkills'

interface SkillModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (input: SkillInput) => void
}

export function SkillModal({ isOpen, onClose, onSubmit }: SkillModalProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [instructions, setInstructions] = useState('')

  useEffect(() => {
    if (isOpen) {
      setName('')
      setDescription('')
      setInstructions('')
    }
  }, [isOpen])

  if (!isOpen) return null

  const canSubmit = name.trim() && instructions.trim()

  const handleSubmit = () => {
    if (!canSubmit) return
    onSubmit({ name, description, instructions })
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in">
      <div className="fixed inset-0" onClick={onClose} />

      <div className="bg-surface dark:bg-surface-dark-secondary max-w-md w-full rounded-2xl overflow-hidden relative z-10 border border-border dark:border-border-dark shadow-xl m-4">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border dark:border-border-dark">
          <h3 className="flex items-center gap-2 font-bold text-sm text-text-primary dark:text-text-dark-primary">
            <Sparkles className="w-4 h-4 text-accent" />
            New skill
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
              placeholder="e.g. Concise code reviewer"
              className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Description <span className="text-text-tertiary font-normal">(optional)</span></label>
            <input
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="What this skill is for"
              className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Instructions</label>
            <textarea
              value={instructions}
              onChange={e => setInstructions(e.target.value)}
              placeholder="Replaces the system prompt whenever this skill is applied to a message…"
              rows={5}
              className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 resize-none scrollbar-thin leading-relaxed"
            />
          </div>
        </div>

        <div className="px-5 py-4 border-t border-border dark:border-border-dark flex items-center justify-end gap-2 bg-surface-secondary dark:bg-surface-dark-tertiary">
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-xs font-semibold hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="px-5 py-2.5 rounded-xl text-xs font-bold bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors"
          >
            Create skill
          </button>
        </div>
      </div>
    </div>
  )
}
