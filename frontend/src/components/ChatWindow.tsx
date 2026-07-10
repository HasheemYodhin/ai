import { useEffect, useRef, useCallback, useState, lazy, Suspense } from 'react'
import type { Message, Project } from '@/types'
import { MessageBubble } from './MessageBubble'
import { InputArea } from './InputArea'
import type { ActiveMode } from './PlusMenu'
import { ModelSwitcher } from './ModelSwitcher'
import { ArtifactProvider, useArtifact } from '@/hooks/useArtifact'
import { cn } from '@/lib/utils'
import { ChevronDown, Ghost } from 'lucide-react'

// Pulls in react-syntax-highlighter (same heavy dep MarkdownRenderer lazy-loads)
// — keep it out of the main bundle and only fetch it once an artifact opens.
const ArtifactPanel = lazy(() => import('./ArtifactPanel').then(mod => ({ default: mod.ArtifactPanel })))

interface ChatWindowProps {
  messages: Message[]
  isLoading: boolean
  onSend: (content: string, images?: string[], opts?: { systemPromptOverride?: string; viaVoice?: boolean }) => void
  onRunAgentMode: (content: string, opts: { label: string; effort?: string; hint?: string; viaVoice?: boolean }) => void
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
}

export function ChatWindow({
  messages, isLoading, onSend, onRunAgentMode, onGenerateImage, onStop, onClear, onEdit, onRegenerate,
  projects, currentProjectId, onAddToProject, initialMode, onInitialModeConsumed, isTemporary,
}: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [showScrollBtn, setShowScrollBtn] = useState(false)
  const [isAutoScroll, setIsAutoScroll] = useState(true)

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
    if (!isAutoScroll) return
    const id = requestAnimationFrame(() => scrollToBottom(false))
    return () => cancelAnimationFrame(id)
  }, [messages, isAutoScroll, scrollToBottom])

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100
    setIsAutoScroll(atBottom)
    setShowScrollBtn(!atBottom)
  }, [])

  const isStreaming = isLoading && messages.length > 0 && messages[messages.length - 1].role === 'assistant'

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
    <span className="flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-full bg-surface-tertiary dark:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary">
      <Ghost className="w-3.5 h-3.5" /> Temporary Chat
    </span>
  )

  const column = messages.length === 0 ? (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between px-6 py-4">
        <ModelSwitcher />
        {temporaryBadge}
      </header>

      <div className="flex-1 flex flex-col items-center justify-center overflow-y-auto scrollbar-thin px-4">
        <div className="w-full max-w-2xl -mt-16">
          <h1 className="text-center text-[28px] font-medium tracking-tight mb-6 text-text-primary dark:text-text-dark-primary">
            {isTemporary ? "This chat won't be saved" : "What's on your mind today?"}
          </h1>
          {inputArea}
        </div>
      </div>
    </div>
  ) : (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between px-6 py-4">
        <div className="flex items-center gap-3">
          <ModelSwitcher />
          {temporaryBadge}
        </div>
        <button
          onClick={onClear}
          className="text-xs px-3 py-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary hover:text-red-500 dark:hover:text-red-400 transition-colors font-medium"
        >
          Clear Chat
        </button>
      </header>

      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto scrollbar-thin px-4 py-6"
      >
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              isStreaming={isStreaming && msg.id === messages[messages.length - 1].id && msg.content === ''}
              onEdit={onEdit}
              onRegenerate={onRegenerate}
            />
          ))}
          <div ref={bottomRef} />
        </div>

        {showScrollBtn && (
          <button
            onClick={() => scrollToBottom(true)}
            className={cn(
              'fixed bottom-28 left-1/2 -translate-x-1/2 p-2.5 rounded-full bg-surface dark:bg-surface-dark-tertiary',
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
    </ArtifactProvider>
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
