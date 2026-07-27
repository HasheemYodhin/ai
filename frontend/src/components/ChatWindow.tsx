import { useEffect, useRef, useCallback, useState, lazy, Suspense } from 'react'
import type { Message, Project, ExtractedDocument, DocumentAttachment } from '@/types'
import { MessageBubble } from './MessageBubble'
import { InputArea } from './InputArea'
import type { ActiveMode } from './PlusMenu'
import { ModelSwitcher } from './ModelSwitcher'
import { ArtifactProvider, useArtifact } from '@/hooks/useArtifact'
import { cn } from '@/lib/utils'
import type { PendingApproval, PendingPlanApproval } from '@/hooks/useChat'
import { ChevronDown, Ghost, ShoppingBag, Wand2, Terminal, Lightbulb, ShieldAlert, ListChecks, type LucideIcon } from 'lucide-react'

// Pulls in react-syntax-highlighter (same heavy dep MarkdownRenderer lazy-loads)
// — keep it out of the main bundle and only fetch it once an artifact opens.
const ArtifactPanel = lazy(() => import('./ArtifactPanel').then(mod => ({ default: mod.ArtifactPanel })))

interface ChatWindowProps {
  messages: Message[]
  isLoading: boolean
  onSend: (content: string, images?: string[], opts?: { systemPromptOverride?: string; viaVoice?: boolean; documents?: ExtractedDocument[]; attachments?: DocumentAttachment[] }) => void
  onRunAgentMode: (content: string, opts: { label: string; effort?: string; hint?: string; viaVoice?: boolean; planMode?: boolean }) => void
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
}

interface Suggestion {
  title: string
  desc: string
  prompt: string
  kind: 'chat' | 'image'
  icon: LucideIcon
}

const SUGGESTIONS: Suggestion[] = [
  {
    title: 'E-Commerce Store',
    desc: 'Create an ecommerce storefront with a slide-out cart panel',
    prompt: 'Create a clean, production-style HTML page for an ecommerce storefront. Include a header with navigation and cart icon, a hero banner, a product grid with sample items, and a footer. All styling should be embedded within the page. Also implement a working add-to-cart option with slide-out cart panel.',
    kind: 'chat',
    icon: ShoppingBag,
  },
  {
    title: 'Ben 10 vs Vilgax',
    desc: 'Generate an action-packed illustration of Ben 10 fighting Vilgax',
    prompt: 'Ben 10 fighting with Vilgax, highly detailed action scene, vibrant colors, anime style',
    kind: 'image',
    icon: Wand2,
  },
  {
    title: 'Python Algorithm',
    desc: 'Write an optimized custom thread-pool executor',
    prompt: 'Write a complete, optimized Python script implementing a custom thread-pool executor. Include a simple demo of scheduling tasks.',
    kind: 'chat',
    icon: Terminal,
  },
  {
    title: 'VS Code Extension Ideas',
    desc: 'Brainstorm creative features for an AI-powered code editor',
    prompt: 'What are some unique features for an AI-powered code editor vscode extension? Brainstorm 5 creative ideas.',
    kind: 'chat',
    icon: Lightbulb,
  }
]

const FOLLOW_UPS = [
  { label: '🔍 Explain in detail', prompt: 'Can you explain the previous answer in more detail, breaking down the key concepts?' },
  { label: '💻 Show code example', prompt: 'Can you show me a complete, runnable code example of this?' },
  { label: '⚡ Optimize this', prompt: 'How can we optimize this solution for better performance or resource usage?' },
  { label: '🐛 Help me debug', prompt: 'I am encountering an issue/error with this. Can you help me debug it?' },
  { label: '❓ Pros & cons', prompt: 'What are the pros and cons of this approach compared to alternatives?' },
  { label: '🛠️ How to run', prompt: 'What are the step-by-step instructions to run and test this code?' },
]

export function ChatWindow({
  messages, isLoading, onSend, onRunAgentMode, onGenerateImage, onStop, onClear, onEdit, onRegenerate,
  projects, currentProjectId, onAddToProject, initialMode, onInitialModeConsumed, isTemporary,
  pendingApproval, onApprovalDecision, pendingPlanApproval, onPlanApprovalDecision,
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

  const followUpRow = messages.length > 0 && !isLoading && (
    <div className="max-w-4xl mx-auto px-4 mb-2">
      <div className="flex items-center gap-2 overflow-x-auto no-scrollbar py-1">
        {FOLLOW_UPS.map((f, idx) => (
          <button
            key={idx}
            onClick={() => onSend(f.prompt)}
            className="flex-shrink-0 px-3.5 py-1.5 rounded-full text-xs font-medium border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary hover:bg-surface-tertiary dark:hover:bg-surface-dark-secondary text-text-secondary dark:text-text-dark-secondary transition-all hover:scale-[1.02] active:scale-[0.98] shadow-sm"
          >
            {f.label}
          </button>
        ))}
      </div>
    </div>
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

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
            {SUGGESTIONS.map((s, idx) => {
              const Icon = s.icon
              return (
                <button
                  key={idx}
                  onClick={() => {
                    if (s.kind === 'image') {
                      onGenerateImage(s.prompt)
                    } else {
                      onSend(s.prompt)
                    }
                  }}
                  className="flex flex-col items-start text-left p-4 rounded-xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary hover:bg-surface-tertiary dark:hover:bg-surface-dark-secondary transition-all hover:scale-[1.01] active:scale-[0.99] group shadow-sm hover:shadow"
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <div className="p-1.5 rounded-lg bg-accent/10 text-accent group-hover:bg-accent group-hover:text-white transition-colors">
                      <Icon className="w-4 h-4" />
                    </div>
                    <span className="text-xs font-semibold text-text-primary dark:text-text-dark-primary">{s.title}</span>
                  </div>
                  <span className="text-[11px] leading-relaxed text-text-secondary dark:text-text-dark-secondary">{s.desc}</span>
                </button>
              )
            })}
          </div>

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
              isStreaming={isStreaming && msg.id === messages[messages.length - 1].id}
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

      {followUpRow}
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
