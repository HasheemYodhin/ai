import { useState } from 'react'
import { BookOpen, Plus, Trash2 } from 'lucide-react'
import { useSkills } from '@/hooks/useSkills'
import { SkillModal } from './SkillModal'

/** Prompt library — reusable saved instructions (Skills), applied as a system-prompt override per message. */
export function SkillsPage() {
  const { skills, createSkill, deleteSkill } = useSkills()
  const [modalOpen, setModalOpen] = useState(false)

  return (
    <div className="flex flex-col h-full overflow-y-auto scrollbar-thin">
      <header className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border-dark">
        <h1 className="text-sm font-bold text-text-primary dark:text-text-dark-primary flex items-center gap-2">
          <BookOpen className="w-4 h-4 text-accent" /> Prompt library
        </h1>
        <button
          onClick={() => setModalOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-semibold transition-colors"
        >
          <Plus className="w-3.5 h-3.5" /> New skill
        </button>
      </header>

      <div className="flex-1 p-6">
        <p className="text-xs text-text-secondary dark:text-text-dark-secondary mb-4">
          Skills are saved instructions you can apply to any message — picking one from the chat "+" menu replaces the system prompt for that message.
        </p>

        {skills.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-text-tertiary">
            <BookOpen className="w-10 h-10 mb-3 opacity-30" />
            <p className="text-sm font-medium">No skills yet</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {skills.map(sk => (
              <div key={sk.id} className="p-4 rounded-2xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-text-primary dark:text-text-dark-primary truncate">{sk.name}</h3>
                  <button
                    onClick={() => deleteSkill(sk.id)}
                    className="p-1 rounded-md hover:bg-surface dark:hover:bg-surface-dark text-text-tertiary hover:text-red-500 transition-colors flex-shrink-0"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                {sk.description && <p className="text-xs text-text-secondary dark:text-text-dark-secondary">{sk.description}</p>}
                <p className="text-[11px] text-text-tertiary dark:text-text-dark-tertiary line-clamp-3 italic">"{sk.instructions}"</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <SkillModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={(input) => createSkill(input)}
      />
    </div>
  )
}
