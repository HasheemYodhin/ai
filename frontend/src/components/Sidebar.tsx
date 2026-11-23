import { useEffect, useState, useRef } from 'react'
import type { Conversation, Project } from '@/types'
import { ConversationList } from './ConversationList'
import { ProjectModal } from './ProjectModal'
import { cn } from '@/lib/utils'
import {
  SquarePen, PanelLeftClose, Settings, Search, Ghost, LogOut, MoreHorizontal,
  MessageSquare, Folder, Bot, Wrench, Plug, BookOpen, Telescope, FolderPlus,
  ChevronDown, X, BriefcaseBusiness, CalendarClock, ListChecks, Webhook,
} from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { useMcpStatus } from '@/hooks/useMcpStatus'
import type { ProjectInput } from '@/hooks/useProjects'
import type { SidebarView } from '@/App'

const PRIMARY_VIEWS: SidebarView[] = ['chat', 'projects', 'cowork', 'agents']
import logo from '../icon.svg'

interface SidebarProps {
  conversations: Conversation[]
  projects: Project[]
  currentId: string | null
  runningConversationIds: string[]
  isOpen: boolean
  view: SidebarView
  onChangeView: (view: SidebarView) => void
  onToggle: () => void
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onRename: (id: string, title: string) => void
  onTogglePin: (id: string) => void
  onAssignToProject: (id: string, projectId: string | null) => void
  onCreateProject: (input: ProjectInput) => string
  onNew: () => void
  onNewTemporary: () => void
  onOpenSettings: () => void
  onStartResearch: () => void
}

export function Sidebar({
  conversations,
  projects,
  currentId,
  runningConversationIds,
  isOpen,
  view,
  onChangeView,
  onToggle,
  onSelect,
  onDelete,
  onRename,
  onTogglePin,
  onAssignToProject,
  onCreateProject,
  onNew,
  onNewTemporary,
  onOpenSettings,
  onStartResearch,
}: SidebarProps) {
  const { currentUser, logout } = useAuth()
  const [projectModalOpen, setProjectModalOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const openSearch = () => {
    setSearchOpen(true)
    requestAnimationFrame(() => searchRef.current?.focus())
  }
  const [profileMenuOpen, setProfileMenuOpen] = useState(false)
  const isSecondaryView = !PRIMARY_VIEWS.includes(view)
  const [moreOpen, setMoreOpen] = useState(isSecondaryView)
  // Opening a page that lives under More reveals its item; the toggle stays the user's after that.
  useEffect(() => {
    if (isSecondaryView) setMoreOpen(true)
  }, [isSecondaryView, view])
  const [projectsOpen, setProjectsOpen] = useState(true)
  const profileRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  // Cheap always-on check just for the little "connected" dot next to Connectors.
  const { servers } = useMcpStatus(true)
  const anyConnected = servers.some(s => s.connected)
  const connectedCount = servers.filter(s => s.connected).length

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault()
        onToggle()
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        if (!isOpen) onToggle()
        onChangeView('chat')
        setSearchOpen(true)
        requestAnimationFrame(() => searchRef.current?.focus())
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onChangeView, onToggle])

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setProfileMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  const navItem = (v: SidebarView, icon: React.ReactNode, label: string, trailing?: React.ReactNode) => (
    <button
      onClick={() => onChangeView(v)}
      aria-current={view === v ? 'page' : undefined}
      className={cn(
        'w-full h-8 flex items-center gap-2.5 px-2.5 rounded-lg text-[13px] font-medium transition-colors',
        view === v
          ? 'bg-accent/10 text-accent'
          : 'text-text-secondary dark:text-text-dark-secondary hover:bg-surface dark:hover:bg-surface-dark-tertiary hover:text-text-primary dark:hover:text-text-dark-primary'
      )}
    >
      {icon}
      <span className="flex-1 text-left truncate">{label}</span>
      {trailing}
    </button>
  )

  const initials = currentUser?.name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase()).join('') || '?'

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/20 z-20 md:hidden"
          onClick={onToggle}
        />
      )}

      <aside
        className={cn(
          'fixed md:relative z-30 h-full flex flex-col transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] [&_svg]:stroke-[1.5]',
          'bg-surface-secondary dark:bg-surface-dark-secondary border-r border-border dark:border-border-dark',
          isOpen ? 'w-[248px] translate-x-0' : 'w-[248px] -translate-x-full md:w-0 md:translate-x-0 md:overflow-hidden md:border-r-0',
        )}
      >
        {/* Brand header */}
        <div className="flex items-center justify-between h-14 pl-4 pr-2.5">
          <div className="flex items-center gap-2">
            <img src={logo} alt="" className="w-5 h-5 object-contain rounded-md" />
            <span className="font-semibold text-base text-text-primary dark:text-text-dark-primary">Dabba</span>
          </div>
          <div className="flex items-center gap-0.5">
            <button
              onClick={onNewTemporary}
              aria-label="New temporary chat, not saved to history" title="New temporary chat, not saved to history"
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors"
            >
              <Ghost className="w-4 h-4" />
            </button>
            <button
              onClick={onToggle}
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors"
              aria-label="Close sidebar (Ctrl+B)" title="Close sidebar (Ctrl+B)"
            >
              <PanelLeftClose className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="px-2.5 space-y-0.5">
          <button
            onClick={onNew}
            className="w-full h-8 flex items-center gap-2.5 px-2.5 rounded-lg text-[13px] font-medium text-text-primary dark:text-text-dark-primary hover:bg-surface dark:hover:bg-surface-dark-tertiary transition-colors"
          >
            <SquarePen className="w-4 h-4 flex-shrink-0" />
            <span className="flex-1 text-left">New chat</span>
          </button>

          {!searchOpen && !search ? (
            <button
              onClick={openSearch}
              className="w-full h-8 flex items-center gap-2.5 px-2.5 rounded-lg text-[13px] font-medium text-text-secondary dark:text-text-dark-secondary hover:bg-surface dark:hover:bg-surface-dark-tertiary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors"
            >
              <Search className="w-4 h-4 flex-shrink-0" />
              <span className="flex-1 text-left">Search chats</span>
              <kbd className="hidden sm:inline-flex px-1 rounded border border-border dark:border-border-dark text-[11px] leading-4 text-text-tertiary font-mono">Ctrl K</kbd>
            </button>
          ) : (
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary dark:text-text-dark-tertiary" />
            <input
              ref={searchRef}
              autoFocus
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              onBlur={() => { if (!search) setSearchOpen(false) }}
              onKeyDown={e => {
                if (e.key === 'Escape') {
                  setSearch('')
                  setSearchOpen(false)
                }
              }}
              placeholder="Search chats"
              aria-label="Search conversations"
              className="w-full h-8 pl-9 pr-9 text-[13px] rounded-lg glass-input
                text-text-primary dark:text-text-dark-primary placeholder:text-text-tertiary dark:placeholder:text-text-dark-tertiary
                focus:border-accent/50 outline-none transition-colors"
            />
            {search && (
              <button
                onMouseDown={e => e.preventDefault()}
                onClick={() => { setSearch(''); searchRef.current?.focus() }}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 rounded text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary"
                aria-label="Clear search"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          )}
        </div>

        {/* Navigation */}
        <div className="px-2.5 pt-4">
          <nav className="space-y-0.5">
            {navItem('chat', <MessageSquare className="w-4 h-4 flex-shrink-0" />, 'Chats',
              <span className="text-xs font-mono tabular-nums text-text-tertiary dark:text-text-dark-tertiary flex-shrink-0">{conversations.length}</span>)}
            {navItem('projects', <Folder className="w-4 h-4 flex-shrink-0" />, 'Projects')}
            {navItem('cowork', <BriefcaseBusiness className="w-4 h-4 flex-shrink-0" />, 'Cowork')}
            {navItem('agents', <Bot className="w-4 h-4 flex-shrink-0" />, 'Agents')}
          </nav>
          {moreOpen && <nav className="space-y-0.5 mt-0.5">
            {navItem('scheduled-skills', <CalendarClock className="w-4 h-4 flex-shrink-0" />, 'Scheduled skills')}
            {navItem('tasks', <ListChecks className="w-4 h-4 flex-shrink-0" />, 'Task center')}
            {navItem('tools', <Wrench className="w-4 h-4 flex-shrink-0" />, 'Tools')}
            {navItem('connectors', <Plug className="w-4 h-4 flex-shrink-0" />, 'Connectors',
              anyConnected && (
                <span className="flex items-center gap-1.5 text-xs text-text-tertiary dark:text-text-dark-tertiary flex-shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-600 dark:bg-green-400" />
                  {connectedCount} live
                </span>
              ))}
            {navItem('skills', <BookOpen className="w-4 h-4 flex-shrink-0" />, 'Prompt library')}
            {navItem('hooks', <Webhook className="w-4 h-4 flex-shrink-0" />, 'Hooks')}
            {navItem('subagents', <Bot className="w-4 h-4 flex-shrink-0" />, 'Subagent types')}
            <button
              onClick={onStartResearch}
              className="w-full h-8 flex items-center gap-2.5 px-2.5 rounded-lg text-[13px] font-medium transition-colors text-text-secondary dark:text-text-dark-secondary hover:bg-surface dark:hover:bg-surface-dark-tertiary hover:text-text-primary dark:hover:text-text-dark-primary"
            >
              <Telescope className="w-4 h-4 flex-shrink-0" />
              <span className="flex-1 text-left">Research mode</span>
            </button>
          </nav>}
          <button
            onClick={() => setMoreOpen(o => !o)}
            aria-expanded={moreOpen}
            className="mt-0.5 w-full h-8 flex items-center gap-2.5 px-2.5 rounded-lg text-[13px] font-medium transition-colors text-text-secondary dark:text-text-dark-secondary hover:bg-surface dark:hover:bg-surface-dark-tertiary hover:text-text-primary dark:hover:text-text-dark-primary"
          >
            <ChevronDown className={cn('w-4 h-4 flex-shrink-0 transition-transform', moreOpen && 'rotate-180')} />
            <span className="flex-1 text-left">{moreOpen ? 'Less' : 'More'}</span>
          </button>
        </div>

        {/* Projects quick list */}
        <div className="px-2.5 pt-6">
          <button
            onClick={() => setProjectsOpen(o => !o)}
            className="w-full flex items-center justify-between px-2.5 pb-2 text-xs text-text-tertiary dark:text-text-dark-tertiary hover:text-text-secondary dark:hover:text-text-dark-secondary transition-colors"
            aria-expanded={projectsOpen}
          >
            <span>Projects <span className="ml-1 font-mono tabular-nums">{projects.length}</span></span>
            <ChevronDown className={cn('w-4 h-4 transition-transform', !projectsOpen && '-rotate-90')} />
          </button>
          {projectsOpen && <div className="max-h-28 overflow-y-auto scrollbar-thin space-y-0.5">
            {projects.map(p => (
              <button
                key={p.id}
                onClick={() => onChangeView('projects')}
                className="w-full h-8 flex items-center gap-2.5 px-2.5 rounded-lg text-[13px] font-medium text-text-secondary dark:text-text-dark-secondary hover:bg-surface dark:hover:bg-surface-dark-tertiary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors"
              >
                <span className="w-4 flex justify-center flex-shrink-0"><span className="w-2 h-2 rounded-full" style={{ background: p.color }} /></span>
                <span className="flex-1 text-left truncate">{p.name}</span>
              </button>
            ))}
            <button
              onClick={() => setProjectModalOpen(true)}
              className="w-full h-8 flex items-center gap-2.5 px-2.5 rounded-lg text-[13px] font-medium text-accent hover:bg-surface dark:hover:bg-surface-dark-tertiary transition-colors"
            >
              <FolderPlus className="w-4 h-4 flex-shrink-0" />
              <span className="flex-1 text-left">New project</span>
            </button>
          </div>}
        </div>

        <div className="flex-1 min-h-0 mt-4 border-t border-border dark:border-border-dark relative">
          <ConversationList
            conversations={conversations}
            projects={projects}
            currentId={currentId}
            runningConversationIds={runningConversationIds}
            search={search}
            onSelect={onSelect}
            onDelete={onDelete}
            onRename={onRename}
            onTogglePin={onTogglePin}
            onAssignToProject={onAssignToProject}
          />
        </div>

        {/* Profile — replaces the old theme toggle (theme now lives in Settings > General) */}
        <div className="p-2 border-t border-border dark:border-border-dark relative" ref={profileRef}>
          <button
            onClick={() => setProfileMenuOpen(o => !o)}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
          >
            <div
              className="w-7 h-7 rounded-full flex items-center justify-center text-white text-xs font-medium flex-shrink-0"
              style={{ background: currentUser?.avatarColor ?? '#c96442' }}
            >
              {initials}
            </div>
            <span className="flex-1 text-left text-sm font-medium text-text-primary dark:text-text-dark-primary truncate">
              {currentUser?.name ?? 'Guest'}
            </span>
            <MoreHorizontal className="w-4 h-4 text-text-tertiary flex-shrink-0" />
          </button>

          {profileMenuOpen && (
            <div className="absolute bottom-full left-3 right-3 mb-1 rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg py-1 animate-fade-in">
              <button
                onClick={() => { setProfileMenuOpen(false); onOpenSettings() }}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-left text-sm text-text-primary dark:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
              >
                <Settings className="w-4 h-4" /> Settings
              </button>
              <button
                onClick={() => { setProfileMenuOpen(false); logout() }}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-left text-sm text-red-500 hover:bg-red-500/10 transition-colors"
              >
                <LogOut className="w-4 h-4" /> Log out
              </button>
            </div>
          )}
        </div>
      </aside>

      <ProjectModal
        isOpen={projectModalOpen}
        onClose={() => setProjectModalOpen(false)}
        onSubmit={(input) => onCreateProject(input)}
      />
    </>
  )
}
