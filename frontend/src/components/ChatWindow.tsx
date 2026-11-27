import { useEffect, useRef, useCallback, useMemo, useState, lazy, Suspense } from 'react'
import type { Message, Project, ExtractedDocument, DocumentAttachment, Conversation } from '@/types'
import { apiClient, type SavedChatMessage } from '@/api/client'
import { MessageBubble } from './MessageBubble'
import { preloadMarkdownRenderer } from '@/lib/markdownRenderer'
import { InputArea } from './InputArea'
import { SavedMessagesDialog, ShareChatDialog } from './ChatExtras'
import type { ActiveMode } from './PlusMenu'
import { ArtifactProvider, useArtifact } from '@/hooks/useArtifact'
import { cn } from '@/lib/utils'
import type { PendingApproval, PendingPlanApproval } from '@/hooks/useChat'
import { Bookmark, ChevronDown, Ghost, Search, Share2, ShieldAlert, ListChecks, BookOpenText, Code2, Gauge, Bug, Scale, Play, MoreHorizontal, Trash2, Lightbulb, FileText, CalendarCheck, X, type LucideIcon } from 'lucide-react'

// Pulls in react-syntax-highlighter (same heavy dep MarkdownRenderer lazy-loads)
// — keep it out of the main bundle and only fetch it once an artifact opens.
const ArtifactPanel = lazy(() => import('./ArtifactPanel').then(mod => ({ default: mod.ArtifactPanel })))

interface ChatWindowProps {
  messages: Message[]
  isLoading: boolean
  onSend: (content: string, images?: string[], opts?: { systemPromptOverride?: string; viaVoice?: boolean; documents?: ExtractedDocument[]; attachments?: DocumentAttachment[] }) => void
  onRunAgentMode: (content: string, opts: { label: string; effort?: string; hint?: string; allowedTools?: string[]; viaVoice?: boolean; planMode?: boolean }) => void
  onGenerateImage: (prompt: string) => void
  onStop: () => void
  onClear: () => void
  onEdit: (id: string, content: string) => void
  onRegenerate: (id: string, overrides?: { model?: string; effort?: string }) => void
  projects: Project[]
  currentProjectId?: string | null
  onAddToProject: (projectId: string) => void
  initialMode?: ActiveMode | null
  onInitialModeConsumed?: () => void
  isTemporary?: boolean
  pendingApproval?: PendingApproval | null
  onApprovalDecision: (approved: boolean) => void
  pendingPlanApproval?: PendingPlanApproval | null
  onPlanApprovalDecision: (approved: boolean) => void
  /** The conversation's saved title, the same one the sidebar shows. */
  conversationTitle?: string
  messageJump?: { id: string; preserveFocus?: boolean } | null
  onMessageJumpComplete?: () => void
  chatId: string | null
  onJump: (chatId: string, messageId: string, preserveFocus?: boolean) => void
  onBranch: (messageId: string) => void
  onRecover: (messageId: string) => Promise<void>
  flushConversation: (chatId: string) => Promise<void>
  loadSharePreview: (chatId: string) => Promise<Conversation>
}

const headerAction = 'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-text-secondary hover:bg-surface-secondary dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary disabled:opacity-50'

const FOLLOW_UPS: { label: string; icon: LucideIcon; prompt: string }[] = [
  { label: 'Explain in detail', icon: BookOpenText, prompt: 'Can you explain the previous answer in more detail, breaking down the key concepts?' },
  { label: 'Show code example', icon: Code2, prompt: 'Can you show me a complete, runnable code example of this?' },
  { label: 'Optimize this', icon: Gauge, prompt: 'How can we optimize this solution for better performance or resource usage?' },
  { label: 'Help me debug', icon: Bug, prompt: 'I am encountering an issue/error with this. Can you help me debug it?' },
  { label: 'Pros and cons', icon: Scale, prompt: 'What are the pros and cons of this approach compared to alternatives?' },
  { label: 'How to run', icon: Play, prompt: 'What are the step-by-step instructions to run and test this code?' },
]

// Starter prompts for the empty state. Clicking one sends it as the first message.
const STARTERS: { label: string; icon: LucideIcon; prompt: string }[] = [
  { label: 'Explain a concept', icon: Lightbulb, prompt: 'Explain how HTTPS keeps data private, in simple terms with an analogy.' },
  { label: 'Write some code', icon: Code2, prompt: 'Write a Python function that removes duplicate items from a list while keeping their order, with a short example.' },
  { label: 'Summarize text', icon: FileText, prompt: 'I will paste some text next. Summarize it in five bullet points and list any action items.' },
  { label: 'Plan something', icon: CalendarCheck, prompt: 'Help me plan a productive week: ask me about my goals, then suggest a simple day-by-day schedule.' },
]

export function ChatWindow({
  messages, isLoading, onSend, onRunAgentMode, onGenerateImage, onStop, onClear, onEdit, onRegenerate,
  projects, currentProjectId, onAddToProject, initialMode, onInitialModeConsumed, isTemporary,
  pendingApproval, onApprovalDecision, pendingPlanApproval, onPlanApprovalDecision,
  conversationTitle, messageJump, onMessageJumpComplete,
  chatId, onJump, onBranch, onRecover, flushConversation, loadSharePreview,
}: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [showScrollBtn, setShowScrollBtn] = useState(false)
  const [isAutoScroll, setIsAutoScroll] = useState(true)
  const [saved, setSaved] = useState<SavedChatMessage[]>([])
  const savedIds = useMemo(() => new Set(saved.filter(item => item.conversation_id === chatId).map(item => item.message_id)), [saved, chatId])
  const [savedOpen, setSavedOpen] = useState(false)
  const [savedLoading, setSavedLoading] = useState(false)
  const [shareFor, setShareFor] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [findFor, setFindFor] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [activeMatch, setActiveMatch] = useState<string | null>(null)
  const findOpen = findFor === (chatId ?? '__temporary__')
  const normalizedQuery = query.trim().toLowerCase()
  const matches = useMemo(() => findOpen && normalizedQuery
    ? messages.filter(message => !message.generatedFiles?.length && message.content.toLowerCase().includes(normalizedQuery))
    : [], [findOpen, messages, normalizedQuery])
  const matchIndex = matches.findIndex(message => message.id === activeMatch)
  const moveMatch = (direction: number) => {
    if (!matches.length) return
    const next = matches[(matchIndex < 0 ? direction < 0 ? matches.length - 1 : 0 : matchIndex + direction + matches.length) % matches.length]
    setActiveMatch(next.id)
    onJump(chatId ?? '__temporary__', next.id, true)
  }

  useEffect(() => {
    let active = true
    apiClient.savedMessages().then(items => { if (active) setSaved(items) }).catch(() => undefined)
    return () => { active = false }
  }, [])

  const openSaved = async () => {
    setSavedOpen(true)
    setSavedLoading(true)
    setActionError('')
    try { setSaved(await apiClient.savedMessages()) }
    catch (err) { setActionError((err as Error).message) }
    finally { setSavedLoading(false) }
  }

  const setSavedMessage = async (id: string, messageId: string, value: boolean) => {
    if (busy) return
    setBusy(true)
    setActionError('')
    try {
      if (value) await flushConversation(id)
      await apiClient.setMessageSaved(id, messageId, value)
      setSaved(await apiClient.savedMessages())
    } catch (err) {
      setActionError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const recover = async (id: string) => {
    setActionError('')
    setBusy(true)
    try { await onRecover(id) }
    catch (err) { setActionError((err as Error).message) }
    finally { setBusy(false) }
  }

  useEffect(() => { preloadMarkdownRenderer() }, [])

  const scrollToBottom = useCallback((smooth = false) => {
    const el = containerRef.current
    if (!el) return
    if (smooth) {
      // Smooth only for discrete jumps (e.g. the "scroll to bottom" button).
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    } else {
      // Instant jump for streaming — setting scrollTop directly has no
      // animation to interrupt, so rapid token updates can't cause the
      // view to bounce up and down.
      el.scrollTop = el.scrollHeight
    }
  }, [])

  // Keep pinned to the bottom as tokens stream in. rAF coalesces the many
  // rapid message updates into one instant scroll per frame.
  useEffect(() => {
    if (!isAutoScroll || (messageJump && messages.some(message => message.id === messageJump.id))) return
    const id = requestAnimationFrame(() => scrollToBottom(false))
    return () => cancelAnimationFrame(id)
  }, [messages, isAutoScroll, scrollToBottom, messageJump])

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100
    setIsAutoScroll(atBottom)
    setShowScrollBtn(!atBottom)
  }, [])

  const isStreaming = isLoading && messages.length > 0 && messages[messages.length - 1].role === 'assistant'
  // Prefer the saved title (auto-generated or renamed) so the header matches
  // the sidebar; fall back to the first prompt line until one exists. The
  // header truncates with an ellipsis via CSS rather than slicing mid-word.
  const savedTitle = conversationTitle && conversationTitle !== 'New conversation' ? conversationTitle : ''
  const title = savedTitle || messages.find(m => m.role === 'user')?.content.split('\n')[0] || 'New chat'

  const inputArea = (
    <InputArea
      onSend={onSend}
      onRunAgentMode={onRunAgentMode}
      onGenerateImage={onGenerateImage}
      onStop={onStop}
      isLoading={isLoading}
      projects={projects}
      currentProjectId={currentProjectId}
      onAddToProject={onAddToProject}
      initialMode={initialMode}
      onInitialModeConsumed={onInitialModeConsumed}
    />
  )

  const temporaryBadge = isTemporary && (
    <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-surface-tertiary dark:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary">
      <Ghost className="w-3.5 h-3.5" strokeWidth={1.5} /> Temporary chat
    </span>
  )

  const [visibleCount, setVisibleCount] = useState(100)
  const jumpIndex = messageJump ? messages.findIndex(message => message.id === messageJump.id) : -1
  const hiddenCount = Math.max(0, Math.min(messages.length - visibleCount, jumpIndex < 0 ? messages.length : jumpIndex))
  useEffect(() => {
    if (!messageJump || jumpIndex < 0) return
    const frame = requestAnimationFrame(() => {
      const target = document.getElementById(`message-${messageJump.id}`)
      target?.scrollIntoView({ block: 'center' })
      if (!messageJump.preserveFocus) target?.focus({ preventScroll: true })
      setVisibleCount(current => Math.max(current, messages.length - jumpIndex))
      setIsAutoScroll(false)
      onMessageJumpComplete?.()
    })
    return () => cancelAnimationFrame(frame)
  }, [messageJump, jumpIndex, messages.length, onMessageJumpComplete])
  const [revealingId, setRevealingId] = useState<string | null>(null)
  const handleRevealChange = useCallback((id: string, revealing: boolean) => {
    setRevealingId(current => revealing ? id : current === id ? null : current)
  }, [])
  const lastMessage = messages[messages.length - 1]
  const showFollowUps = lastMessage?.role === 'assistant' && !isLoading && !lastMessage.error && !lastMessage.generatedFiles?.length && revealingId !== lastMessage.id
  // The chips render only once the reply has finished revealing, i.e. after
  // the streaming auto-scroll ran, so they used to sit below the fold, half
  // hidden behind the composer. Scroll again when they appear.
  useEffect(() => {
    if (!showFollowUps || !isAutoScroll) return
    const id = requestAnimationFrame(() => scrollToBottom(false))
    return () => cancelAnimationFrame(id)
  }, [showFollowUps, isAutoScroll, scrollToBottom])
  const followUpRow = showFollowUps && (
    <div className="flex flex-wrap gap-2 pl-10">
      {FOLLOW_UPS.map((f, idx) => (
        <button
          key={idx}
          onClick={() => onSend(f.prompt)}
          className="h-8 flex items-center gap-2 px-3 rounded-full text-[13px] border border-border dark:border-border-dark hover:bg-surface-secondary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-[background-color,transform] active:scale-[0.98]"
        >
          <f.icon className="w-4 h-4 text-text-tertiary dark:text-text-dark-tertiary" strokeWidth={1.5} />
          {f.label}
        </button>
      ))}
    </div>
  )

  const column = messages.length === 0 ? (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between h-14 shrink-0 px-4 sm:px-6">
        <span className="text-[15px] font-medium text-text-primary dark:text-text-dark-primary">Dabba</span>
        {!isTemporary && <button type="button" className={headerAction} title="Saved messages" aria-label="Saved messages" onClick={() => void openSaved()}><Bookmark size={17} /></button>}
        {temporaryBadge}
      </header>

      <div className="flex-1 flex flex-col items-center overflow-y-auto scrollbar-thin px-3 py-4 sm:justify-center sm:px-4 sm:py-0">
        <div className="my-auto w-full max-w-2xl shrink-0 sm:my-0 sm:-mt-16">
          <h1 className="text-center font-display text-[28px] leading-tight font-semibold tracking-[-0.03em] mb-4 sm:mb-8 sm:text-[36px] text-text-primary dark:text-text-dark-primary">
            {isTemporary ? "This chat won't be saved" : 'Chat, write code or make an image'}
          </h1>

          {inputArea}

          <div className="mt-2 grid grid-cols-1 gap-2 px-1 sm:grid-cols-2 sm:px-4">
            {STARTERS.map(starter => (
              <button
                key={starter.label}
                onClick={() => onSend(starter.prompt)}
                disabled={isLoading}
                className="flex items-start gap-3 rounded-2xl border border-border p-3 text-left transition-colors hover:bg-surface-secondary disabled:opacity-50 dark:border-border-dark dark:hover:bg-surface-dark-tertiary"
              >
                <starter.icon className="mt-0.5 h-4 w-4 flex-shrink-0 text-accent" strokeWidth={1.5} aria-hidden="true" />
                <span className="min-w-0">
                  <span className="block text-[13px] font-medium text-text-primary dark:text-text-dark-primary">{starter.label}</span>
                  <span className="mt-0.5 block text-xs text-text-secondary line-clamp-2 dark:text-text-dark-secondary">{starter.prompt}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  ) : (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between h-14 shrink-0 px-4 sm:px-6">
        <div className="flex items-center gap-3 min-w-0">
          <span className="truncate text-[15px] font-medium text-text-primary dark:text-text-dark-primary" title={title}>{title}</span>
          {temporaryBadge}
        </div>
        <div className="flex shrink-0 items-center">
          <button type="button" className={headerAction} title="Find in chat" aria-label="Find in chat" aria-expanded={findOpen}
            onClick={() => { setFindFor(findOpen ? null : (chatId ?? '__temporary__')); setQuery(''); setActiveMatch(null) }}><Search size={17} /></button>
          {!isTemporary && <>
            <button type="button" className={headerAction} title="Saved messages" aria-label="Saved messages" onClick={() => void openSaved()}><Bookmark size={17} /></button>
            <button type="button" className={headerAction} title="Share chat" aria-label="Share chat" disabled={!chatId || isLoading}
              onClick={() => setShareFor(chatId)}><Share2 size={17} /></button>
          </>}
          <ConversationActionsMenu onClear={onClear} />
        </div>
      </header>
      {findOpen && (
        <div role="search" aria-label="Find in chat" className="flex flex-wrap items-center gap-1 border-b border-border p-2 dark:border-border-dark sm:px-6">
          <input autoFocus aria-label="Search this chat" placeholder="Find a message…" value={query}
            className="min-w-24 flex-1 rounded-lg border border-border bg-transparent px-2 py-1 text-base dark:border-border-dark sm:text-sm"
            onChange={event => { setQuery(event.currentTarget.value); setActiveMatch(null) }}
            onKeyDown={event => {
              if (event.key === 'Enter') { event.preventDefault(); moveMatch(event.shiftKey ? -1 : 1) }
              if (event.key === 'Escape') setFindFor(null)
            }} />
          <span role="status" className="px-1 text-xs">{matchIndex >= 0 ? `${matchIndex + 1}/${matches.length}` : `${matches.length} matches`}</span>
          <button type="button" className={headerAction} aria-label="Previous match" disabled={!matches.length} onClick={() => moveMatch(-1)}>↑</button>
          <button type="button" className={headerAction} aria-label="Next match" disabled={!matches.length} onClick={() => moveMatch(1)}>↓</button>
          <button type="button" className={headerAction} aria-label="Close find" onClick={() => setFindFor(null)}><X size={16} /></button>
        </div>
      )}
      {!!actionError && !savedOpen && <p role="alert" className="px-4 py-1 text-sm text-red-600 dark:text-red-400">{actionError}</p>}

      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto overflow-x-hidden scrollbar-thin px-4 pt-6 pb-10"
      >
        <div className="max-w-3xl mx-auto space-y-6">
          {hiddenCount > 0 && (
            <button
              className="mx-auto block text-sm text-accent hover:underline"
              onClick={() => setVisibleCount(count => count + 100)}
            >
              Show earlier messages ({hiddenCount})
            </button>
          )}
          {messages.slice(hiddenCount).map((msg) => (
            <div key={msg.id} id={`message-${msg.id}`} tabIndex={-1}
              className={cn('rounded-lg focus-visible:outline focus-visible:outline-accent', findOpen && msg.id === activeMatch && normalizedQuery && 'ring-2 ring-accent')}>
            <MessageBubble
              message={msg}
              isStreaming={isStreaming && msg.id === messages[messages.length - 1].id}
              onRevealChange={handleRevealChange}
              onEdit={onEdit}
              onRegenerate={onRegenerate}
              saved={savedIds.has(msg.id)}
              onSave={chatId && !isTemporary && !isLoading && !busy ? value => void setSavedMessage(chatId, msg.id, value) : undefined}
              onBranch={!isTemporary && !isLoading ? () => onBranch(msg.id) : undefined}
              onRecover={!isLoading && msg.recoveryRequestId && !busy ? () => void recover(msg.id) : undefined}
              onSourceJump={messageId => onJump(chatId ?? '__temporary__', messageId)}
            />
            </div>
          ))}
          {followUpRow}
          {lastMessage?.interrupted && !isLoading && (
            <button
              className="ml-10 rounded-lg border border-border px-3 py-1.5 text-sm text-accent dark:border-border-dark"
              onClick={() => onSend('Continue from where you stopped without repeating the previous text.')}
              disabled={!navigator.onLine}
            >
              Continue reply
            </button>
          )}
          <div ref={bottomRef} />
        </div>

        {showScrollBtn && (
          <button
            onClick={() => scrollToBottom(true)}
            aria-label="Scroll to latest message"
            className={cn(
              'sticky bottom-2 left-1/2 -translate-x-1/2 p-2.5 rounded-full bg-surface dark:bg-surface-dark-tertiary',
              'border border-border dark:border-border-dark text-accent shadow-md hover:bg-surface-tertiary dark:hover:bg-surface-dark',
              'transition-colors z-10 animate-fade-in'
            )}
          >
            <ChevronDown className="w-5 h-5" />
          </button>
        )}
      </div>

      {inputArea}
    </div>
  )

  return (
    <ArtifactProvider>
      <div className="flex h-full min-w-0">
        <div className="flex-1 min-w-0">
          {column}
        </div>
        <ArtifactPanelSlot />
      </div>
      {pendingApproval && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4 backdrop-blur-sm">
          <div role="dialog" aria-modal="true" aria-labelledby="tool-approval-title" className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl dark:border-border-dark dark:bg-surface-dark-secondary">
            <div className="flex items-start gap-3 border-b border-border px-5 py-4 dark:border-border-dark">
              <span className="mt-0.5 rounded-xl bg-amber-500/10 p-2 text-amber-500"><ShieldAlert className="h-5 w-5" /></span>
              <div>
                <h2 id="tool-approval-title" className="text-sm font-semibold text-text-primary dark:text-text-dark-primary">Allow this action?</h2>
                <p className="mt-1 text-xs leading-relaxed text-text-secondary dark:text-text-dark-secondary">
                  Dabba is waiting for permission to run <code className="rounded bg-surface-tertiary px-1 py-0.5 text-[11px] dark:bg-surface-dark-tertiary">{pendingApproval.name}</code>. The task remains paused until you choose.
                </p>
              </div>
            </div>
            <div className="px-5 py-4">
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-surface-secondary p-3 text-[11px] leading-relaxed text-text-secondary dark:bg-surface-dark dark:text-text-dark-secondary">{JSON.stringify(pendingApproval.arguments, null, 2)}</pre>
            </div>
            <div className="flex justify-end gap-2 border-t border-border bg-surface-secondary px-5 py-4 dark:border-border-dark dark:bg-surface-dark-tertiary">
              <button onClick={() => onApprovalDecision(false)} className="rounded-xl border border-border px-4 py-2 text-xs font-semibold text-text-secondary transition-colors hover:bg-surface-tertiary dark:border-border-dark dark:text-text-dark-secondary dark:hover:bg-surface-dark-secondary">Deny</button>
              <button autoFocus onClick={() => onApprovalDecision(true)} className="rounded-xl bg-accent px-5 py-2 text-xs font-semibold text-white transition-colors hover:bg-accent-hover">Allow and continue</button>
            </div>
          </div>
        </div>
      )}
      {pendingPlanApproval && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4 backdrop-blur-sm">
          <div role="dialog" aria-modal="true" aria-labelledby="plan-approval-title" className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl dark:border-border-dark dark:bg-surface-dark-secondary">
            <div className="flex items-start gap-3 border-b border-border px-5 py-4 dark:border-border-dark">
              <span className="mt-0.5 rounded-xl bg-accent/10 p-2 text-accent"><ListChecks className="h-5 w-5" /></span>
              <div>
                <h2 id="plan-approval-title" className="text-sm font-semibold text-text-primary dark:text-text-dark-primary">Run this plan?</h2>
                <p className="mt-1 text-xs leading-relaxed text-text-secondary dark:text-text-dark-secondary">
                  Dabba wants to run a {pendingPlanApproval.steps.length}-step plan before replying. Nothing executes until you choose.
                </p>
              </div>
            </div>
            <div className="max-h-72 overflow-auto px-5 py-4">
              <ol className="space-y-2">
                {pendingPlanApproval.steps.map((step, i) => (
                  <li key={step.step_id} className="flex gap-2 text-xs text-text-secondary dark:text-text-dark-secondary">
                    <span className="mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full bg-surface-tertiary text-[10px] font-semibold text-text-tertiary dark:bg-surface-dark-tertiary">{i + 1}</span>
                    <span>
                      <code className="rounded bg-surface-tertiary px-1 py-0.5 text-[11px] dark:bg-surface-dark-tertiary">{step.tool}</code>{' '}
                      {step.description}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
            <div className="flex justify-end gap-2 border-t border-border bg-surface-secondary px-5 py-4 dark:border-border-dark dark:bg-surface-dark-tertiary">
              <button onClick={() => onPlanApprovalDecision(false)} className="rounded-xl border border-border px-4 py-2 text-xs font-semibold text-text-secondary transition-colors hover:bg-surface-tertiary dark:border-border-dark dark:text-text-dark-secondary dark:hover:bg-surface-dark-secondary">Skip plan</button>
              <button autoFocus onClick={() => onPlanApprovalDecision(true)} className="rounded-xl bg-accent px-5 py-2 text-xs font-semibold text-white transition-colors hover:bg-accent-hover">Run plan</button>
            </div>
          </div>
        </div>
      )}
      {savedOpen && <SavedMessagesDialog items={saved} loading={savedLoading} error={actionError}
        onClose={() => { setSavedOpen(false); setActionError('') }}
        onOpen={item => { setSavedOpen(false); onJump(item.conversation_id, item.message_id) }}
        onRemove={item => void setSavedMessage(item.conversation_id, item.message_id, false)} />}
      {shareFor && shareFor === chatId && <ShareChatDialog chatId={shareFor} loadPreview={loadSharePreview} onClose={() => setShareFor(null)} />}
    </ArtifactProvider>
  )
}

// "⋯" menu in the chat header. Holds destructive actions (Clear chat) so they
// don't sit next to the title as plain text.
function ConversationActionsMenu({ onClear }: { onClear: () => void }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div ref={rootRef} className="relative flex-shrink-0">
      <button
        ref={buttonRef}
        onClick={() => setOpen(o => !o)}
        aria-label="Conversation actions"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Conversation actions"
        className="p-1.5 rounded-lg text-text-secondary transition-colors hover:bg-surface-tertiary hover:text-text-primary dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary dark:hover:text-text-dark-primary"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-30 mt-1 w-44 rounded-xl border border-border bg-surface py-1 shadow-lg dark:border-border-dark dark:bg-surface-dark-secondary">
          <button
            role="menuitem"
            autoFocus
            onClick={() => {
              setOpen(false)
              if (window.confirm('Clear all messages in this chat? This cannot be undone.')) onClear()
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-600 transition-colors hover:bg-surface-tertiary dark:text-red-400 dark:hover:bg-surface-dark-tertiary"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            Clear chat
          </button>
        </div>
      )}
    </div>
  )
}

// Only mounts (and therefore only fetches) the lazy ArtifactPanel chunk once
// an artifact has actually been opened at least once this session.
function ArtifactPanelSlot() {
  const { artifact } = useArtifact()
  const [everOpened, setEverOpened] = useState(false)
  useEffect(() => {
    if (artifact) setEverOpened(true)
  }, [artifact])

  if (!everOpened) return null
  return (
    <Suspense fallback={null}>
      <ArtifactPanel />
    </Suspense>
  )
}
