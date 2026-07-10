import { useState } from 'react'
import type { Conversation, Project } from '@/types'
import type { ProjectInput } from '@/hooks/useProjects'
import { ProjectModal } from './ProjectModal'
import { Folder, Plus, Pencil, Trash2, MessageSquarePlus } from 'lucide-react'

interface ProjectsPageProps {
  projects: Project[]
  conversations: Conversation[]
  onCreateProject: (input: ProjectInput) => string
  onUpdateProject: (id: string, updates: Partial<ProjectInput>) => void
  onDeleteProject: (id: string) => void
  onNewChatInProject: (projectId: string) => void
}

export function ProjectsPage({
  projects, conversations, onCreateProject, onUpdateProject, onDeleteProject, onNewChatInProject,
}: ProjectsPageProps) {
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Project | null>(null)

  const countFor = (id: string) => conversations.filter(c => c.projectId === id).length

  return (
    <div className="flex flex-col h-full overflow-y-auto scrollbar-thin">
      <header className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border-dark">
        <h1 className="text-sm font-bold text-text-primary dark:text-text-dark-primary flex items-center gap-2">
          <Folder className="w-4 h-4 text-accent" /> Projects
        </h1>
        <button
          onClick={() => { setEditing(null); setModalOpen(true) }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-semibold transition-colors"
        >
          <Plus className="w-3.5 h-3.5" /> New project
        </button>
      </header>

      <div className="flex-1 p-6">
        {projects.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-text-tertiary dark:text-text-dark-tertiary">
            <Folder className="w-10 h-10 mb-3 opacity-30" />
            <p className="text-sm font-medium">No projects yet</p>
            <p className="text-xs mt-1">Group related conversations and give them shared instructions.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map(p => (
              <div key={p.id} className="p-4 rounded-2xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: p.color }} />
                  <h3 className="text-sm font-semibold text-text-primary dark:text-text-dark-primary truncate flex-1">{p.name}</h3>
                </div>
                {p.description && (
                  <p className="text-xs text-text-secondary dark:text-text-dark-secondary line-clamp-2">{p.description}</p>
                )}
                {p.instructions && (
                  <p className="text-[11px] text-text-tertiary dark:text-text-dark-tertiary line-clamp-2 italic">"{p.instructions}"</p>
                )}
                <div className="flex items-center justify-between mt-1 pt-2 border-t border-border dark:border-border-dark">
                  <span className="text-[10px] text-text-tertiary">{countFor(p.id)} conversation{countFor(p.id) === 1 ? '' : 's'}</span>
                  <div className="flex items-center gap-0.5">
                    <button
                      onClick={() => onNewChatInProject(p.id)}
                      title="New chat in this project"
                      className="p-1.5 rounded-md hover:bg-surface dark:hover:bg-surface-dark text-text-tertiary hover:text-accent transition-colors"
                    >
                      <MessageSquarePlus className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => { setEditing(p); setModalOpen(true) }}
                      title="Edit project"
                      className="p-1.5 rounded-md hover:bg-surface dark:hover:bg-surface-dark text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => confirm(`Delete project "${p.name}"? Conversations stay, just unassigned.`) && onDeleteProject(p.id)}
                      title="Delete project"
                      className="p-1.5 rounded-md hover:bg-surface dark:hover:bg-surface-dark text-text-tertiary hover:text-red-500 transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <ProjectModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={(input) => editing ? onUpdateProject(editing.id, input) : onCreateProject(input)}
        initial={editing}
      />
    </div>
  )
}
