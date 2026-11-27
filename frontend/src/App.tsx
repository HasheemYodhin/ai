import { useState, useCallback, useEffect, useRef } from 'react'
import { PanelLeft } from 'lucide-react'
import { ThemeProvider } from '@/hooks/useTheme'
import { SettingsProvider } from '@/hooks/useSettings'
import { AuthProvider, useAuth } from '@/hooks/useAuth'
import { useChat } from '@/hooks/useChat'
import { useHistory } from '@/hooks/useHistory'
import { useProjects } from '@/hooks/useProjects'
import { Sidebar } from '@/components/Sidebar'
import { ChatWindow } from '@/components/ChatWindow'
import { SharedChatPage } from '@/components/ChatExtras'
import { SettingsModal } from '@/components/SettingsModal'
import { AuthPage } from '@/components/AuthPage'
import { LegalPage, NotFoundPage } from '@/components/PublicPages'
import { GuestChatPage, dismissGuestImport, readPendingGuestImport } from '@/components/GuestChatPage'
import { LandingPage } from '@/components/LandingPage'
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
import { AdminOnlyNotice } from '@/components/AdminOnlyNotice'
import { ADMIN_ONLY_VIEWS, ADMIN_VIEW_LABELS } from '@/lib/adminViews'
import type { ActiveMode } from '@/components/PlusMenu'
import type { ExtractedDocument, DocumentAttachment, Message } from '@/types'
import { RESEARCH_MODE } from '@/lib/agentModes'
import { cn } from '@/lib/utils'
import { apiClient } from '@/api/client'
import { parsePath, pathFor } from '@/lib/routes'

export type SidebarView = 'chat' | 'projects' | 'cowork' | 'scheduled-skills' | 'tasks' | 'agents' | 'tools' | 'connectors' | 'skills' | 'hooks' | 'subagents'

function isMobileLayout() {
  return !window.matchMedia('(min-width: 768px)').matches
}

function ChatApp() {
  const { currentUser, isAdmin } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(() => !isMobileLayout())
  const [isSettingsOpen, setSettingsOpen] = useState(false)
  // The URL decides the first view and which chat to reopen (see lib/routes.ts).
  const [initialRoute] = useState(() => parsePath(window.location.pathname))
  const [view, setView] = useState<SidebarView>(initialRoute.view)
  const [pendingMode, setPendingMode] = useState<ActiveMode | null>(null)
  // Temporary chats never touch the backend — see the auto-save effect below
  // and ensureConversation(), both of which are no-ops while this is true.
  const [isTemporaryChat, setIsTemporaryChat] = useState(false)
  const { notices: processNotices, dismiss: dismissProcessNotice } = useProcessNotifications(isAdmin)
  const {
    conversations,
    currentId,
    isLoading: isHistoryLoading,
    hasUnsavedChanges,
    retrySaves,
    saveConflictCopy,
    deleteError,
    createConversation,
    saveConversation,
    flushConversation,
    loadConversationAsync,
    getConversation,
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
    recoverReply,
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
    if (currentId || isTemporaryChat) {
      setRestoredUserId(currentUserId)
      return
    }

    const storageKey = `dabba_current_conversation_id_${currentUserId}`
    // A /c/:id link wins; otherwise reopen the last chat on a chat-view load.
    // An unknown or foreign id simply opens a new chat (the URL is corrected).
    const storedId = initialRoute.conversationId ?? localStorage.getItem(storageKey)
    const targetId = (storedId && conversations.some(c => c.id === storedId))
      ? storedId
      : null

    if (targetId) {
      // The sidebar list is lightweight (no messages); fetch the chat's
      // messages if they aren't loaded yet, e.g. when opening a /c/:id link.
      void loadConversationAsync(targetId).then(conv => {
        if (conv) setMessages([...conv.messages], targetId)
      })
    }
    setRestoredUserId(currentUserId)
  }, [conversations, currentId, currentUserId, restoredUserId, isHistoryLoading, isTemporaryChat, loadConversationAsync, setMessages, initialRoute])

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
  // getConversation also sees the unsaved draft chat, which isn't in `conversations`.
  const currentProjectId = getConversation(currentId)?.projectId ?? null
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

  const [pendingGuestImport, setPendingGuestImport] = useState(readPendingGuestImport)
  const closeGuestImport = () => {
    dismissGuestImport()
    setPendingGuestImport([])
  }

  const importGuestChat = () => {
    if (!pendingGuestImport.length || isHistoryLoading) return
    if (currentId && messages.length && !isTemporaryChat) saveConversation(messages, currentId)
    const imported = pendingGuestImport.map(message => ({
      id: crypto.randomUUID(),
      role: message.role,
      content: message.content,
      timestamp: Date.now(),
    }))
    const id = createConversation(imported)
    setMessages(imported, id)
    setIsTemporaryChat(false)
    setView('chat')
    closeGuestImport()
  }

  const [messageJump, setMessageJump] = useState<{ id: string; preserveFocus?: boolean } | null>(null)
  const clearMessageJump = useCallback(() => setMessageJump(null), [])
  const handleSelectConversation = useCallback((id: string, messageId?: string) => {
    if (id === currentId) {
      if (messageId) setMessageJump({ id: messageId })
      return
    }
    setMessageJump(null)

    if (currentId && messages.length > 0 && !isTemporaryChat) {
      saveConversation(messages, currentId)
    }

    // Messages load on demand (the sidebar list carries only metadata).
    void loadConversationAsync(id).then(conv => {
      if (!conv) return
      // Copy the array so React always commits the selected conversation,
      // even if its message array was previously used by the chat view.
      setMessages([...conv.messages], id)
      if (messageId) setMessageJump({ id: messageId })
      setIsTemporaryChat(false)
    })
  }, [currentId, isTemporaryChat, loadConversationAsync, messages, saveConversation, setMessages])

  const jumpToMessage = useCallback((id: string, messageId: string, preserveFocus = false) => {
    if (id === currentId || id === '__temporary__') setMessageJump({ id: messageId, preserveFocus })
    else handleSelectConversation(id, messageId)
    setView('chat')
  }, [currentId, handleSelectConversation])

  const branchChat = (messageId: string) => {
    const index = messages.findIndex(message => message.id === messageId)
    if (index < 0 || isLoading || isTemporaryChat) return
    const branch = messages.slice(0, index + 1).map(message => ({ ...message, recoveryRequestId: undefined }))
    setMessageJump(null)
    const id = createConversation(branch)
    setMessages(branch, id)
    if (currentProjectId) assignToProject(id, currentProjectId)
  }

  const loadSharePreview = useCallback(async (id: string) => {
    await flushConversation(id)
    return apiClient.fetchConversation(id)
  }, [flushConversation])

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

  const closeMobileSidebar = () => {
    if (isMobileLayout()) setSidebarOpen(false)
  }

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

  // ── URL sync (B4) ──────────────────────────────────────────────────────
  // State → URL. A chat only gets /c/:id once it has messages, so "New chat"
  // stays at `/` and an unsaved draft never becomes a dead link.
  const routedConversationId = view === 'chat' && !isTemporaryChat && messages.length > 0 ? currentId : null
  const lastPathRef = useRef<string | null>(null)
  const applyingPopStateRef = useRef(false)
  useEffect(() => {
    // Wait until the restore effect above has decided which chat is open.
    if (!currentUserId || restoredUserId !== currentUserId) return
    const path = pathFor(view, routedConversationId)
    const previous = lastPathRef.current
    lastPathRef.current = path
    if (window.location.pathname === path) { applyingPopStateRef.current = false; return }
    // Replace instead of push for: the first sync (fixes unknown or stale
    // URLs), Back/Forward navigation, and a new chat at `/` getting its id
    // after the first message — none of these should add a history entry.
    const replace = previous === null || applyingPopStateRef.current
      || (previous === '/' && routedConversationId !== null)
    applyingPopStateRef.current = false
    if (replace) window.history.replaceState(null, '', path)
    else window.history.pushState(null, '', path)
  }, [view, routedConversationId, currentUserId, restoredUserId])

  // URL → state on Back/Forward. Handlers are read through a ref so this
  // listener is registered once and always calls the latest callbacks.
  const popStateHandlersRef = useRef({ currentId, handleSelectConversation, handleNewChat })
  popStateHandlersRef.current = { currentId, handleSelectConversation, handleNewChat }
  useEffect(() => {
    const onPopState = () => {
      const route = parsePath(window.location.pathname)
      const { currentId: openId, handleSelectConversation: select, handleNewChat: startNew } = popStateHandlersRef.current
      applyingPopStateRef.current = true
      setView(route.view)
      if (route.view !== 'chat') return
      if (route.conversationId && route.conversationId !== openId) select(route.conversationId)
      else if (!route.conversationId && messages.length > 0) startNew()
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [messages.length])

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
        onSelect={(id, messageId) => {
          handleSelectConversation(id, messageId)
          setView('chat')
          closeMobileSidebar()
        }}
        onDelete={handleDeleteConversation}
        onRename={renameConversation}
        onTogglePin={togglePin}
        onAssignToProject={assignToProject}
        onCreateProject={createProject}
        onNew={() => {
          handleNewChat()
          setView('chat')
          closeMobileSidebar()
        }}
        onNewTemporary={() => {
          handleNewTemporaryChat()
          closeMobileSidebar()
        }}
        onOpenSettings={() => {
          setSettingsOpen(true)
          closeMobileSidebar()
        }}
        onStartResearch={() => {
          handleStartResearch()
          closeMobileSidebar()
        }}
      />

      <main className={cn(
        // Landing page look: a white rounded card inset on the off-white shell (md and up).
        'flex-1 flex flex-col min-w-0 bg-surface dark:bg-surface-dark border-l border-border dark:border-border-dark overflow-hidden relative z-10',
        'md:my-2 md:mr-2 md:rounded-[24px] md:border md:border-border md:shadow-[0_1px_2px_rgba(0,0,0,0.04)] dark:md:border-border-dark',
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

        {pendingGuestImport.length > 0 && (
          <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2 text-xs dark:border-border-dark">
            <span>Save the guest conversation from this browser to your account?</span>
            <button type="button" onClick={importGuestChat} disabled={isHistoryLoading} className="text-accent underline disabled:opacity-50">Import guest chat</button>
            <button type="button" onClick={closeGuestImport} className="text-text-secondary">Dismiss</button>
          </div>
        )}
        {(saveConflictCopy || deleteError) && (
          <div role="alert" className="px-4 py-2 text-xs text-text-secondary">
            {deleteError}
            {saveConflictCopy && (
              <button className="text-accent underline" onClick={saveConflictCopy}>
                Conversation changed elsewhere. Save your edits as a copy
              </button>
            )}
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
            messageJump={messageJump}
            onMessageJumpComplete={clearMessageJump}
            conversationTitle={isTemporaryChat ? undefined : getConversation(currentId)?.title}
            chatId={currentId}
            onJump={jumpToMessage}
            onBranch={branchChat}
            onRecover={recoverReply}
            flushConversation={flushConversation}
            loadSharePreview={loadSharePreview}
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
        {/* Admin-only pages: regular users get an explanation instead of a
            form whose requests all fail with 403. */}
        {!isAdmin && ADMIN_ONLY_VIEWS.has(view) && (
          <div className="flex-1 min-h-0"><AdminOnlyNotice feature={ADMIN_VIEW_LABELS[view] ?? 'This page'} /></div>
        )}
        {isAdmin && view === 'cowork' && <div className="flex-1 min-h-0"><CoworkWorkspace /></div>}
        {isAdmin && view === 'scheduled-skills' && <div className="flex-1 min-h-0"><ScheduledSkillsPage /></div>}
        {view === 'tasks' && <div className="flex-1 min-h-0"><TaskCenterPage /></div>}
        {view === 'agents' && <div className="flex-1 min-h-0"><AgentsPage /></div>}
        {isAdmin && view === 'tools' && <div className="flex-1 min-h-0"><ToolsPage /></div>}
        {isAdmin && view === 'connectors' && <div className="flex-1 min-h-0"><ConnectorsPage onOpenSkills={() => setView('skills')} /></div>}
        {view === 'skills' && <div className="flex-1 min-h-0"><SkillsPage /></div>}
        {isAdmin && view === 'hooks' && <div className="flex-1 min-h-0"><HooksPage /></div>}
        {isAdmin && view === 'subagents' && <div className="flex-1 min-h-0"><SubagentsPage /></div>}
      </main>
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  )
}

type PublicScreen = 'home' | 'try' | 'login' | 'signup' | 'privacy' | 'terms' | 'not-found'

const PUBLIC_PATHS: Partial<Record<PublicScreen, string>> = {
  home: '/', try: '/try', login: '/login', signup: '/signup', privacy: '/privacy', terms: '/terms',
}

function publicScreenFor(pathname: string): PublicScreen {
  const path = pathname.replace(/\/+$/, '') || '/'
  for (const [screen, screenPath] of Object.entries(PUBLIC_PATHS)) {
    if (screenPath === path) return screen as PublicScreen
  }
  // App addresses (/c/:id, /agents, ...) need a login: show the login form;
  // after login the app opens that address. Anything else is a 404.
  const route = parsePath(path)
  if (route.conversationId || route.view !== 'chat') return 'login'
  return 'not-found'
}

/**
 * Signed out: `/` is the landing page, `/try` the free guest chat,
 * `/login` and `/signup` the auth form,
 * `/privacy` and `/terms` the legal pages, and unknown paths a 404.
 * Signed in: the app (legal pages stay reachable).
 */
function AuthGate() {
  const { currentUser, isReady } = useAuth()
  const [screen, setScreen] = useState<PublicScreen>(() => publicScreenFor(window.location.pathname))
  const [shareId, setShareId] = useState(() => /^\/share\/([A-Za-z0-9_-]{32})\/?$/.exec(window.location.pathname)?.[1])

  useEffect(() => {
    const onPopState = () => {
      setScreen(publicScreenFor(window.location.pathname))
      setShareId(/^\/share\/([A-Za-z0-9_-]{32})\/?$/.exec(window.location.pathname)?.[1])
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const go = useCallback((next: PublicScreen, replace = false) => {
    const path = PUBLIC_PATHS[next] ?? '/'
    if (window.location.pathname !== path) {
      if (replace) window.history.replaceState(null, '', path)
      else window.history.pushState(null, '', path)
    }
    setScreen(next)
    window.scrollTo(0, 0)
  }, [])

  // After signing in from /login or /signup, start the app at `/`.
  useEffect(() => {
    if (currentUser && (window.location.pathname === '/login' || window.location.pathname === '/signup')) {
      window.history.replaceState(null, '', '/')
    }
  }, [currentUser])

  if (shareId) return <SharedChatPage key={shareId} id={shareId} />
  if (!isReady) {
    return <div className="flex h-full items-center justify-center bg-surface text-sm text-text-secondary dark:bg-surface-dark dark:text-text-dark-secondary">Restoring your Dabba session...</div>
  }
  if (screen === 'privacy' || screen === 'terms') return <LegalPage kind={screen} onHome={() => go('home')} onSwitch={kind => go(kind)} />
  if (currentUser) return <ChatApp />
  if (screen === 'try') return <GuestChatPage onLogin={() => go('login')} onSignup={() => go('signup')} onHome={() => go('home')} />
  if (screen === 'not-found') return <NotFoundPage onHome={() => go('home')} />
  if (screen === 'home') return <LandingPage onTry={() => go('try')} onLogin={() => go('login')} onSignup={() => go('signup')} onNavigate={path => go(path === '/privacy' ? 'privacy' : 'terms')} />
  return <AuthPage initialMode={screen === 'signup' ? 'signup' : 'login'} onModeChange={mode => go(mode, true)} onHome={() => go('home')} />
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
