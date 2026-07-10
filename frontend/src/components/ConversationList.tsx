import { useState, useMemo, useCallback, useRef, useEffect, type KeyboardEvent } from 'react'
import type { Conversation, Project } from '@/types'
import { cn, formatRelativeTime, truncate } from '@/lib/utils'
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

/** Last model that actually replied in this conversation, for the badge next to each chat. */
function lastModel(conv: Conversation): string | undefined {
  for (let i = conv.messages.length - 1; i >= 0; i--) {
    const m = conv.messages[i]
    if (m.role === 'assistant' && m.model) return m.model
  }
  return undefined
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
      <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-text-tertiary dark:text-text-dark-tertiary">
        Recent Chats
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 pb-2" onClick={() => setMoveMenuFor(null)}>
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-text-tertiary dark:text-text-dark-tertiary">
            <MessageSquare className="w-8 h-8 mb-2 opacity-30" />
            <p className="text-xs font-medium">{search.trim() ? 'No matching chats' : 'No conversations yet'}</p>
            {search.trim() && <p className="mt-1 text-[10px] opacity-75">Try a different search</p>}
          </div>
        ) : (
          <div className="space-y-1">
            {filtered.map((conv) => {
              const project = conv.projectId ? projects.find(p => p.id === conv.projectId) : undefined
              const model = lastModel(conv)
              return (
                <div
                  key={conv.id}
                  onClick={() => editingId !== conv.id && handleSelect(conv.id)}
                  className={cn(
                    'w-full text-left px-3 py-2.5 rounded-lg transition-colors group relative cursor-pointer',
                    conv.id === currentId
                      ? 'bg-surface dark:bg-surface-dark-tertiary text-text-primary dark:text-text-dark-primary'
                      : 'bg-transparent hover:bg-surface dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary hover:text-text-primary dark:hover:text-text-dark-primary'
                  )}
                >
                  <div className="flex items-start gap-2.5">
                    {project ? (
                      <span className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0" style={{ background: project.color }} title={project.name} />
                    ) : conv.pinned ? (
                      <Pin className="w-4 h-4 mt-0.5 flex-shrink-0 text-accent" />
                    ) : (
                      <MessageSquare className="w-4 h-4 mt-0.5 flex-shrink-0 opacity-60" />
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
                          className="w-full text-sm font-medium bg-transparent border-b border-accent outline-none text-text-primary dark:text-text-dark-primary"
                        />
                      ) : (
                        <p className="text-sm font-medium truncate">
                          {truncate(conv.title, 40)}
                        </p>
                      )}
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-[10px] opacity-70 font-medium">
                          {formatRelativeTime(conv.updatedAt)}
                        </span>
                        {model && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-surface-tertiary dark:bg-surface-dark-tertiary text-text-tertiary dark:text-text-dark-tertiary truncate max-w-[100px]">
                            {model}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-0.5 opacity-100 md:opacity-0 md:group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity flex-shrink-0 relative">
                      <button
                        onClick={(e) => { e.stopPropagation(); onTogglePin(conv.id) }}
                        className="p-1.5 rounded-md hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-tertiary hover:text-accent transition-colors"
                        title={conv.pinned ? 'Unpin' : 'Pin'}
                      >
                        {conv.pinned ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />}
                      </button>
                      <button
                        onClick={(e) => startRename(e, conv)}
                        className="p-1.5 rounded-md hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors"
                        title="Rename"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setMoveMenuFor(moveMenuFor === conv.id ? null : conv.id) }}
                        className="p-1.5 rounded-md hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors"
                        title="Add to project"
                      >
                        <MoreHorizontal className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={(e) => handleDelete(e, conv.id)}
                        className={cn(
                          'p-1.5 rounded-md transition-colors',
                          confirmDelete === conv.id
                            ? 'bg-red-100 dark:bg-red-900/30 text-red-500'
                            : 'hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-tertiary hover:text-red-500'
                        )}
                        title={confirmDelete === conv.id ? 'Confirm delete' : 'Delete conversation'}
                      >
                        {confirmDelete === conv.id ? (
                          <AlertTriangle className="w-3.5 h-3.5" />
                        ) : (
                          <Trash2 className="w-3.5 h-3.5" />
                        )}
                      </button>

                      {moveMenuFor === conv.id && (
                        <div
                          onClick={e => e.stopPropagation()}
                          className="absolute right-0 top-full mt-1 w-48 rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-30 py-1 animate-fade-in"
                        >
                          <div className="px-3 py-1 text-[9px] font-semibold uppercase tracking-wider text-text-tertiary">Move to project</div>
                          {projects.map(p => (
                            <button
                              key={p.id}
                              onClick={() => { onAssignToProject(conv.id, p.id); setMoveMenuFor(null) }}
                              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors text-xs"
                            >
                              <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: p.color }} />
                              <span className="truncate text-text-primary dark:text-text-dark-primary">{p.name}</span>
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
                          {projects.length === 0 && (
                            <p className="px-3 py-2 text-[10px] text-text-tertiary">No projects yet — create one from Projects in the sidebar.</p>
                          )}
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
