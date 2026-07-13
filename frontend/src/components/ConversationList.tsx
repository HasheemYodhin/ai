import { useState, useMemo, useCallback, useRef, useEffect, type KeyboardEvent } from 'react'
import type { Conversation, Project } from '@/types'
import { cn, truncate } from '@/lib/utils'
import {
  Trash2, MessageSquare, AlertTriangle, Pin, PinOff, Pencil,
  FolderMinus, MoreHorizontal,
} from 'lucide-react'

interface ConversationListProps {
  conversations: Conversation[]
  projects: Project[]
  currentId: string | null
  /** Controlled from the sidebar — its search box sits right under "New Chat" now, not in this list. */
  search: string
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onRename: (id: string, title: string) => void
  onTogglePin: (id: string) => void
  onAssignToProject: (id: string, projectId: string | null) => void
}

export function ConversationList({
  conversations,
  projects,
  currentId,
  search,
  onSelect,
  onDelete,
  onRename,
  onTogglePin,
  onAssignToProject,
}: ConversationListProps) {
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [moveMenuFor, setMoveMenuFor] = useState<string | null>(null)
  const editInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editingId) editInputRef.current?.select()
  }, [editingId])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const base = q ? conversations.filter(c => c.title.toLowerCase().includes(q)) : conversations
    return [...base].sort((a, b) => {
      if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1
      return b.updatedAt - a.updatedAt
    })
  }, [conversations, search])

  const handleDelete = useCallback((e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    if (confirmDelete === id) {
      onDelete(id)
      setConfirmDelete(null)
    } else {
      setConfirmDelete(id)
    }
  }, [confirmDelete, onDelete])

  const handleSelect = useCallback((id: string) => {
    setConfirmDelete(null)
    onSelect(id)
  }, [onSelect])

  const startRename = useCallback((e: React.MouseEvent, conv: Conversation) => {
    e.stopPropagation()
    setEditingId(conv.id)
    setEditValue(conv.title)
  }, [])

  const commitRename = useCallback(() => {
    if (editingId && editValue.trim()) {
      onRename(editingId, editValue.trim())
    }
    setEditingId(null)
  }, [editingId, editValue, onRename])

  const handleRenameKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      commitRename()
    } else if (e.key === 'Escape') {
      setEditingId(null)
    }
  }, [commitRename])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 pt-2 pb-1 text-[9px] font-semibold uppercase tracking-[0.12em] text-text-tertiary dark:text-text-dark-tertiary">
        <span>Recent</span>
        <span className="font-normal tracking-normal">{filtered.length}</span>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 pb-2" onClick={() => setMoveMenuFor(null)}>
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-text-tertiary dark:text-text-dark-tertiary">
            <MessageSquare className="w-8 h-8 mb-2 opacity-30" />
            <p className="text-xs font-medium">{search.trim() ? 'No matching chats' : 'No conversations yet'}</p>
            {search.trim() && <p className="mt-1 text-[10px] opacity-75">Try a different search</p>}
          </div>
        ) : (
          <div className="space-y-0.5">
            {filtered.map((conv) => {
              const project = conv.projectId ? projects.find(p => p.id === conv.projectId) : undefined
              return (
                <div
                  key={conv.id}
                  onClick={() => editingId !== conv.id && handleSelect(conv.id)}
                  className={cn(
                    'w-full text-left px-2 py-1.5 rounded-lg transition-colors group relative cursor-pointer',
                    conv.id === currentId
                      ? 'bg-surface dark:bg-surface-dark-tertiary text-text-primary dark:text-text-dark-primary'
                      : 'bg-transparent hover:bg-surface dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary hover:text-text-primary dark:hover:text-text-dark-primary'
                  )}
                >
                  <div className="flex items-center gap-2">
                    {project ? (
                      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: project.color }} title={project.name} />
                    ) : conv.pinned ? (
                      <Pin className="w-3.5 h-3.5 flex-shrink-0 text-accent" />
                    ) : (
                      <MessageSquare className="w-3.5 h-3.5 flex-shrink-0 opacity-50" />
                    )}
                    <div className="flex-1 min-w-0">
                      {editingId === conv.id ? (
                        <input
                          ref={editInputRef}
                          value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          onKeyDown={handleRenameKeyDown}
                          onBlur={commitRename}
                          onClick={e => e.stopPropagation()}
                          className="w-full text-[13px] font-medium bg-transparent border-b border-accent outline-none text-text-primary dark:text-text-dark-primary"
                        />
                      ) : (
                        <p className="text-[13px] leading-5 font-medium truncate">
                          {truncate(conv.title, 40)}
                        </p>
                      )}
                    </div>

                    <div className="relative flex-shrink-0 opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 group-focus-within:opacity-100">
                      <button
                        onClick={(e) => { e.stopPropagation(); setMoveMenuFor(moveMenuFor === conv.id ? null : conv.id) }}
                        className="p-1 rounded-md hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors"
                        title="Conversation actions"
                      >
                        <MoreHorizontal className="w-3.5 h-3.5" />
                      </button>

                      {moveMenuFor === conv.id && (
                        <div
                          onClick={e => e.stopPropagation()}
                          className="absolute right-0 top-full mt-1 w-44 rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-30 py-1 animate-fade-in"
                        >
                          <button onClick={() => { onTogglePin(conv.id); setMoveMenuFor(null) }} className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs text-text-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary">
                            {conv.pinned ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />} {conv.pinned ? 'Unpin' : 'Pin'}
                          </button>
                          <button onClick={(e) => { setMoveMenuFor(null); startRename(e, conv) }} className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs text-text-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary">
                            <Pencil className="w-3.5 h-3.5" /> Rename
                          </button>
                          {projects.length > 0 && <div className="my-1 border-t border-border dark:border-border-dark" />}
                          {projects.map(projectItem => (
                            <button
                              key={projectItem.id}
                              onClick={() => { onAssignToProject(conv.id, projectItem.id); setMoveMenuFor(null) }}
                              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors text-xs"
                            >
                              <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: projectItem.color }} />
                              <span className="truncate text-text-primary dark:text-text-dark-primary">Move to {projectItem.name}</span>
                            </button>
                          ))}
                          {conv.projectId && (
                            <button
                              onClick={() => { onAssignToProject(conv.id, null); setMoveMenuFor(null) }}
                              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors text-xs text-text-secondary"
                            >
                              <FolderMinus className="w-3.5 h-3.5" /> Remove from project
                            </button>
                          )}
                          <div className="my-1 border-t border-border dark:border-border-dark" />
                          <button onClick={(e) => handleDelete(e, conv.id)} className={cn('w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors', confirmDelete === conv.id ? 'bg-red-500/10 text-red-500' : 'text-red-500 hover:bg-red-500/10')}>
                            {confirmDelete === conv.id ? <AlertTriangle className="w-3.5 h-3.5" /> : <Trash2 className="w-3.5 h-3.5" />}
                            {confirmDelete === conv.id ? 'Click again to delete' : 'Delete'}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
