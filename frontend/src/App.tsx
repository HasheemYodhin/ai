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
import { CoworkWorkspace } from '@/components/CoworkWorkspace'
import { ScheduledSkillsPage } from '@/components/ScheduledSkillsPage'
import { HooksPage } from '@/components/HooksPage'
import { SubagentsPage } from '@/components/SubagentsPage'
import { useProcessNotifications } from '@/hooks/useRunNotifications'
import { CheckCircle2, XCircle, X } from 'lucide-react'
import { TaskCenterPage } from '@/components/TaskCenterPage'
import type { ActiveMode } from '@/components/PlusMenu'
import type { ExtractedDocument, DocumentAttachment, Message } from '@/types'
import { RESEARCH_MODE } from '@/lib/agentModes'
import { cn } from '@/lib/utils'
import { apiClient } from '@/api/client'

export type SidebarView = 'chat' | 'projects' | 'cowork' | 'scheduled-skills' | 'tasks' | 'agents' | 'tools' | 'connectors' | 'skills' | 'hooks' | 'subagents'

function ChatApp() {
  const { currentUser } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [isSettingsOpen, setSettingsOpen] = useState(false)
  const [view, setView] = useState<SidebarView>('chat')
  const [pendingMode, setPendingMode] = useState<ActiveMode | null>(null)
  // Temporary chats never touch the backend — see the auto-save effect below
  // and ensureConversation(), both of which are no-ops while this is true.
  const [isTemporaryChat, setIsTemporaryChat] = useState(false)
  const { notices: processNotices, dismiss: dismissProcessNotice } = useProcessNotifications()
  const {
    conversations,
    currentId,
    isLoading: isHistoryLoading,
    hasUnsavedChanges,
    retrySaves,
    createConversation,
    saveConversation,
    loadConversation,
    deleteConversation,
    renameConversation,
    togglePin,
    assignToProject,
    setCurrentId,
  } = useHistory(currentUser?.id ?? null)

  const [isOffline, setIsOffline] = useState(() => !navigator.onLine)
  useEffect(() => {
    const update = () => setIsOffline(!navigator.onLine)
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => {
      window.removeEventListener('online', update)
      window.removeEventListener('offline', update)
    }
  }, [])

  const handleConversationUpdate = useCallback((conversationId: string, nextMessages: Message[]) => {
    if (conversationId === '__temporary__') return
    saveConversation(nextMessages, conversationId)
  }, [saveConversation])

  const {
    messages,
    isLoading,
    runningConversationIds,
    sendMessage,
    runAgentMode,
    generateImage,
    stopGeneration,
    clearMessages,
    setMessages,
    editMessage,
    regenerate,
    pendingApproval,
    respondToApproval,
    pendingPlanApproval,
    respondToPlanApproval,
  } = useChat({
    activeConversationId: isTemporaryChat ? '__temporary__' : currentId,
    onConversationUpdate: handleConversationUpdate,
    onConversationTitle: renameConversation,
  })

  const { projects, createProject, updateProject, deleteProject } = useProjects()

  const currentUserId = currentUser?.id ?? null
  const [restoredUserId, setRestoredUserId] = useState<string | null>(null)

  // Persist the active conversation ID in localStorage when it changes (only after initial restore has run)
  useEffect(() => {
    if (!currentUser || restoredUserId !== currentUser.id) return
    const storageKey = `dabba_current_conversation_id_${currentUser.id}`
    if (currentId) {
      localStorage.setItem(storageKey, currentId)
    } else {
      localStorage.removeItem(storageKey)
    }
  }, [currentId, currentUser, restoredUserId])

  // Restore the last active conversation on initial load/refresh once history is loaded

  useEffect(() => {
    if (!currentUserId || restoredUserId === currentUserId || isHistoryLoading) return

    const storageKey = `dabba_current_conversation_id_${currentUserId}`
    const storedId = localStorage.getItem(storageKey)
    const targetId = (storedId && conversations.some(c => c.id === storedId))
      ? storedId
      : null

    if (targetId) {
      setCurrentId(targetId)
      const conv = conversations.find(c => c.id === targetId)
      if (conv) {
        setMessages([...conv.messages], targetId)
      }
    }
    setRestoredUserId(currentUserId)
  }, [conversations, currentUserId, restoredUserId, isHistoryLoading, setCurrentId, setMessages])

  // Web search and image generation start their own fresh conversation the
  // same way a normal message does — ensure one exists before sending.
  // No-op for temporary chats: currentId stays null on purpose.
  const ensureConversation = useCallback(() => {
    if (isTemporaryChat) return '__temporary__'
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

  const handleSend = useCallback((content: string, images?: string[], opts?: { systemPromptOverride?: string; viaVoice?: boolean; documents?: ExtractedDocument[]; attachments?: DocumentAttachment[] }) => {
    const conversationId = ensureConversation()
    if (!conversationId) return
    const systemPromptOverride = opts?.systemPromptOverride ?? currentProject?.instructions
    sendMessage(content, images, { conversationId, systemPromptOverride, viaVoice: opts?.viaVoice, documents: opts?.documents, attachments: opts?.attachments })
  }, [ensureConversation, sendMessage, currentProject])

  const handleRunAgentMode = useCallback((content: string, opts: { label: string; effort?: string; hint?: string; allowedTools?: string[]; viaVoice?: boolean; planMode?: boolean }) => {
    const conversationId = ensureConversation()
    if (!conversationId) return
    runAgentMode(content, { ...opts, conversationId })
  }, [ensureConversation, runAgentMode])

  const handleGenerateImage = useCallback((prompt: string) => {
    const conversationId = ensureConversation()
    if (!conversationId) return
    generateImage(prompt, conversationId)
  }, [ensureConversation, generateImage])

  const handleAddCurrentToProject = useCallback((projectId: string) => {
    const id = ensureConversation()
    if (id) assignToProject(id, projectId)
  }, [ensureConversation, assignToProject])

  const handleNewChat = useCallback(() => {
    if (currentId && messages.length > 0 && !isTemporaryChat) saveConversation(messages, currentId)
    const id = createConversation()
    setMessages([], id)
    setIsTemporaryChat(false)
  }, [createConversation, currentId, isTemporaryChat, messages, saveConversation, setMessages])

  const handleNewTemporaryChat = useCallback(() => {
    setCurrentId(null)
    setIsTemporaryChat(true)
    setMessages([], '__temporary__')
    setView('chat')
  }, [setCurrentId, setMessages])

  const handleSelectConversation = useCallback((id: string) => {
    if (id === currentId) return

    if (currentId && messages.length > 0 && !isTemporaryChat) {
      saveConversation(messages, currentId)
    }

    const conv = loadConversation(id)
    if (conv) {
      // Copy the array so React always commits the selected conversation,
      // even if its message array was previously used by the chat view.
      setMessages([...conv.messages], id)
      setIsTemporaryChat(false)
    }
  }, [currentId, isTemporaryChat, loadConversation, messages, saveConversation, setMessages])

  const handleDeleteConversation = useCallback((id: string) => {
    if (currentId === id) {
      stopGeneration()
      clearMessages()
    }
    void apiClient.releaseAgentConversation(id)
    deleteConversation(id)
  }, [currentId, clearMessages, deleteConversation, stopGeneration])

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
      {processNotices.length > 0 && (
        <div className="pointer-events-none fixed right-4 top-4 z-50 flex w-80 flex-col gap-2">
          {processNotices.map(notice => (
            <div key={notice.id} className={cn(
              'pointer-events-auto flex items-start gap-2 rounded-xl border p-3 text-xs shadow-lg backdrop-blur',
              notice.tone === 'success' ? 'border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-300'
                : 'border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-300'
            )}>
              {notice.tone === 'success' ? <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />}
              <span className="flex-1">{notice.message}</span>
              <button onClick={() => dismissProcessNotice(notice.id)} className="text-current opacity-60 hover:opacity-100"><X className="h-3.5 w-3.5" /></button>
            </div>
          ))}
        </div>
      )}
      <Sidebar
        conversations={conversations}
        projects={projects}
        currentId={currentId}
        runningConversationIds={runningConversationIds}
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

        {(isOffline || hasUnsavedChanges) && (
          <div role="status" className="flex items-center gap-3 border-b border-border px-4 py-2 text-sm dark:border-border-dark">
            {isOffline && <span>You’re offline.</span>}
            {hasUnsavedChanges && (
              <button className="text-accent underline" onClick={retrySaves}>
                Conversation not saved. Retry
              </button>
            )}
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
            pendingApproval={pendingApproval}
            onApprovalDecision={respondToApproval}
            pendingPlanApproval={pendingPlanApproval}
            onPlanApprovalDecision={respondToPlanApproval}
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
        {view === 'cowork' && <div className="flex-1 min-h-0"><CoworkWorkspace /></div>}
        {view === 'scheduled-skills' && <div className="flex-1 min-h-0"><ScheduledSkillsPage /></div>}
        {view === 'tasks' && <div className="flex-1 min-h-0"><TaskCenterPage /></div>}
        {view === 'agents' && <div className="flex-1 min-h-0"><AgentsPage /></div>}
        {view === 'tools' && <div className="flex-1 min-h-0"><ToolsPage /></div>}
        {view === 'connectors' && <div className="flex-1 min-h-0"><ConnectorsPage onOpenSkills={() => setView('skills')} /></div>}
        {view === 'skills' && <div className="flex-1 min-h-0"><SkillsPage /></div>}
        {view === 'hooks' && <div className="flex-1 min-h-0"><HooksPage /></div>}
        {view === 'subagents' && <div className="flex-1 min-h-0"><SubagentsPage /></div>}
      </main>
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  )
}

function AuthGate() {
  const { currentUser, isReady } = useAuth()
  if (!isReady) {
    return <div className="flex h-full items-center justify-center bg-surface text-sm text-text-secondary dark:bg-surface-dark dark:text-text-dark-secondary">Restoring your Dabba session...</div>
  }
  return currentUser ? <ChatApp /> : <AuthPage />
}

export default function App() {
  return (
    <ThemeProvider>
      <SettingsProvider>
        <AuthProvider>
          <AuthGate />
        </AuthProvider>
      </SettingsProvider>
    </ThemeProvider>
  )
}
