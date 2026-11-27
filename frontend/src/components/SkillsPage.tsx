import { useState } from 'react'
import { BookOpen, Download, Plus, Trash2 } from 'lucide-react'
import { useSkills } from '@/hooks/useSkills'
import { SkillModal } from './SkillModal'
import { SkillImportModal } from './SkillImportModal'

/** Prompt library — reusable saved instructions (Skills), applied as a system-prompt override per message. */
export function SkillsPage() {
  const { skills, createSkill, importSkill, deleteSkill } = useSkills()
  const [modalOpen, setModalOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  return (
    <div className="flex flex-col h-full overflow-y-auto scrollbar-thin">
      <header className="flex items-center justify-between h-14 px-6 border-b border-border dark:border-border-dark">
        <h1 className="text-[15px] font-medium text-text-primary dark:text-text-dark-primary">Prompt library</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setImportOpen(true)}
            className="h-8 flex items-center gap-2 px-3 rounded-lg border border-border dark:border-border-dark text-text-primary dark:text-text-dark-primary hover:bg-surface-secondary dark:hover:bg-surface-dark-tertiary text-[13px] transition-colors"
          >
            <Download className="w-4 h-4" strokeWidth={1.5} /> Import skill
          </button>
          <button
            onClick={() => setModalOpen(true)}
            className="h-8 flex items-center gap-2 px-3 rounded-lg bg-accent hover:bg-accent-hover text-white text-[13px] font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> New skill
          </button>
        </div>
      </header>

      <div className="flex-1 p-6">
        <p className="text-[13px] text-text-secondary dark:text-text-dark-secondary mb-6 max-w-2xl">
          Skills are saved instructions. Dabba applies the best match to a message automatically, or you can pick one from the chat + menu. Import any SKILL.md file to add it here
        </p>

        {skills.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-text-tertiary">
            <BookOpen className="w-8 h-8 mb-3 opacity-40" strokeWidth={1.5} />
            <p className="text-[13px]">No skills yet</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {skills.map(sk => (
              <div key={sk.id} className="group p-4 rounded-xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-[13px] font-medium text-text-primary dark:text-text-dark-primary truncate">{sk.name}</h3>
                  <button
                    onClick={() => void deleteSkill(sk.id)}
                    aria-label={`Delete ${sk.name}`}
                    className="p-1.5 rounded-lg text-text-tertiary hover:text-red-600 hover:bg-surface dark:hover:bg-surface-dark transition-colors flex-shrink-0 md:opacity-0 md:group-hover:opacity-100 focus:opacity-100"
                  >
                    <Trash2 className="w-4 h-4" strokeWidth={1.5} />
                  </button>
                </div>
                {sk.description && <p className="text-xs leading-5 text-text-secondary dark:text-text-dark-secondary line-clamp-3">{sk.description}</p>}
                <p className="text-xs leading-5 text-text-tertiary dark:text-text-dark-tertiary line-clamp-2 font-mono">{sk.instructions}</p>
                {sk.script && <code className="mt-1 truncate rounded bg-surface-tertiary px-1.5 py-1 text-xs text-text-tertiary dark:bg-surface-dark-secondary">{sk.script}</code>}
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
      <SkillImportModal
        isOpen={importOpen}
        onClose={() => setImportOpen(false)}
        onImport={importSkill}
      />
    </div>
  )
}
