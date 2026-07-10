import { useState, useCallback, useEffect } from 'react'
import { PanelLeft } from 'lucide-react'
import { ThemeProvider } from '@/hooks/useTheme'
import { SettingsProvider } from '@/hooks/useSettings'
import { AuthProvider, useAuth } from '@/hooks/useAuth'
import { useChat } from '@/hooks/useChat'
import { useHistory } from '@/hooks/useHistory'
import { useProjects } from '@/hooks/useProjects'
import { Sidebar } from '@/components/Sidebar'
import { ChatWindow } from '@/components/ChatWindow'
import { SettingsModal } from '@/components/SettingsModal'
import { AuthPage } from '@/components/AuthPage'
import { ProjectsPage } from '@/components/ProjectsPage'
import { AgentsPage } from '@/components/AgentsPage'
import { ToolsPage } from '@/components/ToolsPage'
import { ConnectorsPage } from '@/components/ConnectorsPage'
import { SkillsPage } from '@/components/SkillsPage'
import type { ActiveMode } from '@/components/PlusMenu'
import { RESEARCH_MODE } from '@/lib/agentModes'
import { cn } from '@/lib/utils'

export type SidebarView = 'chat' | 'projects' | 'agents' | 'tools' | 'connectors' | 'skills'

function ChatApp() {
  const { currentUser } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [isSettingsOpen, setSettingsOpen] = useState(false)
  const [view, setView] = useState<SidebarView>('chat')
  const [pendingMode, setPendingMode] = useState<ActiveMode | null>(null)
  // Temporary chats never touch the backend — see the auto-save effect below
  // and ensureConversation(), both of which are no-ops while this is true.
  const [isTemporaryChat, setIsTemporaryChat] = useState(false)
  const {
    messages,
    isLoading,
    sendMessage,
    runAgentMode,
    generateImage,
    stopGeneration,
    clearMessages,
    setMessages,
    editMessage,
    regenerate,
  } = useChat()

  const {
    conversations,
    currentId,
    createConversation,
    saveConversation,
    loadConversation,
    deleteConversation,
    renameConversation,
    togglePin,
    assignToProject,
    setCurrentId,
  } = useHistory(currentUser?.id ?? null)

  const { projects, createProject, updateProject, deleteProject } = useProjects()

  // Auto-save conversation when messages change — skipped entirely for
  // temporary chats, which only ever live in useChat's in-memory state.
  useEffect(() => {
    if (messages.length > 0 && !isTemporaryChat) {
      saveConversation(messages)
    }
  }, [messages, isTemporaryChat])

  // Web search and image generation start their own fresh conversation the
  // same way a normal message does — ensure one exists before sending.
  // No-op for temporary chats: currentId stays null on purpose.
  const ensureConversation = useCallback(() => {
    if (isTemporaryChat) return currentId
    if (!currentId) {
      const id = createConversation()
      setCurrentId(id)
      return id
    }
    return currentId
  }, [currentId, createConversation, setCurrentId, isTemporaryChat])

  // A skill (explicit, per-message) always wins over a project's automatic
  // instructions; if neither is set, useChat falls back to the global system prompt.
  const currentProjectId = conversations.find(c => c.id === currentId)?.projectId ?? null
  const currentProject = projects.find(p => p.id === currentProjectId) ?? null

  const handleSend = useCallback((content: string, images?: string[], opts?: { systemPromptOverride?: string; viaVoice?: boolean }) => {
    ensureConversation()
    const systemPromptOverride = opts?.systemPromptOverride ?? currentProject?.instructions
    sendMessage(content, images, { systemPromptOverride, viaVoice: opts?.viaVoice })
  }, [ensureConversation, sendMessage, currentProject])

  const handleRunAgentMode = useCallback((content: string, opts: { label: string; effort?: string; hint?: string; viaVoice?: boolean }) => {
    ensureConversation()
    runAgentMode(content, opts)
  }, [ensureConversation, runAgentMode])

  const handleGenerateImage = useCallback((prompt: string) => {
    ensureConversation()
    generateImage(prompt)
  }, [ensureConversation, generateImage])

  const handleAddCurrentToProject = useCallback((projectId: string) => {
    const id = ensureConversation()
    if (id) assignToProject(id, projectId)
  }, [ensureConversation, assignToProject])

  const handleNewChat = useCallback(() => {
    clearMessages()
    setCurrentId(null)
    setIsTemporaryChat(false)
  }, [clearMessages, setCurrentId])

  const handleNewTemporaryChat = useCallback(() => {
    clearMessages()
    setCurrentId(null)
    setIsTemporaryChat(true)
    setView('chat')
  }, [clearMessages, setCurrentId])

  const handleSelectConversation = useCallback((id: string) => {
    const conv = loadConversation(id)
    if (conv) {
      setMessages(conv.messages)
      setIsTemporaryChat(false)
    }
  }, [loadConversation, setMessages])

  const handleDeleteConversation = useCallback((id: string) => {
    if (currentId === id) {
      clearMessages()
    }
    deleteConversation(id)
  }, [currentId, clearMessages, deleteConversation])

  const toggleSidebar = useCallback(() => {
    setSidebarOpen(prev => !prev)
  }, [])

  // "Research mode" in the sidebar nav: start a fresh chat pre-armed with the
  // Research agent-mode preset (same one available from the "+" menu).
  const handleStartResearch = useCallback(() => {
    handleNewChat()
    setPendingMode({ kind: 'agent', ...RESEARCH_MODE })
    setView('chat')
  }, [handleNewChat])

  const handleNewChatInProject = useCallback((projectId: string) => {
    handleNewChat()
    const id = createConversation()
    setCurrentId(id)
    assignToProject(id, projectId)
    setView('chat')
  }, [handleNewChat, createConversation, setCurrentId, assignToProject])

  return (
    <div className="flex h-full overflow-hidden bg-surface-secondary dark:bg-surface-dark relative">
      <Sidebar
        conversations={conversations}
        projects={projects}
        currentId={currentId}
        isOpen={sidebarOpen}
        view={view}
        onChangeView={setView}
        onToggle={toggleSidebar}
        onSelect={(id) => { handleSelectConversation(id); setView('chat') }}
        onDelete={handleDeleteConversation}
        onRename={renameConversation}
        onTogglePin={togglePin}
        onAssignToProject={assignToProject}
        onCreateProject={createProject}
        onNew={() => { handleNewChat(); setView('chat') }}
        onNewTemporary={handleNewTemporaryChat}
        onOpenSettings={() => setSettingsOpen(true)}
        onStartResearch={handleStartResearch}
      />

      <main className={cn(
        'flex-1 flex flex-col min-w-0 bg-surface dark:bg-surface-dark border-l border-border dark:border-border-dark overflow-hidden relative z-10',
        sidebarOpen ? 'md:ml-0' : ''
      )}>
        {/* Reopen control lives here, in normal layout flow, instead of a
            floating fixed button — a floating button at top-left used to sit
            directly on top of the chat header's ModelSwitcher whenever the
            sidebar was closed. This slot is shared by every view (Chats,
            Projects, Agents, …) so it never has anything to collide with. */}
        {!sidebarOpen && (
          <div className="flex items-center px-3 py-2 border-b border-border dark:border-border-dark flex-shrink-0">
            <button
              onClick={toggleSidebar}
              className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors"
              title="Open sidebar (Ctrl+B)"
            >
              <PanelLeft className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* ChatWindow stays mounted while browsing other views so an in-flight
            generation keeps running in the background; other views render on top. */}
        <div className={cn('flex-1 min-h-0', view !== 'chat' && 'hidden')}>
          <ChatWindow
            messages={messages}
            isLoading={isLoading}
            onSend={handleSend}
            onRunAgentMode={handleRunAgentMode}
            onGenerateImage={handleGenerateImage}
            onStop={stopGeneration}
            onClear={clearMessages}
            onEdit={editMessage}
            onRegenerate={regenerate}
            projects={projects}
            currentProjectId={currentProjectId}
            onAddToProject={handleAddCurrentToProject}
            initialMode={pendingMode}
            onInitialModeConsumed={() => setPendingMode(null)}
            isTemporary={isTemporaryChat}
          />
        </div>

        {view === 'projects' && (
          <div className="flex-1 min-h-0">
            <ProjectsPage
              projects={projects}
              conversations={conversations}
              onCreateProject={createProject}
              onUpdateProject={updateProject}
              onDeleteProject={deleteProject}
              onNewChatInProject={handleNewChatInProject}
            />
          </div>
        )}
        {view === 'agents' && <div className="flex-1 min-h-0"><AgentsPage /></div>}
        {view === 'tools' && <div className="flex-1 min-h-0"><ToolsPage /></div>}
        {view === 'connectors' && <div className="flex-1 min-h-0"><ConnectorsPage /></div>}
        {view === 'skills' && <div className="flex-1 min-h-0"><SkillsPage /></div>}
      </main>
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  )
}

function AuthGate() {
  const { currentUser } = useAuth()
  return currentUser ? <ChatApp /> : <AuthPage />
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <SettingsProvider>
          <AuthGate />
        </SettingsProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}
