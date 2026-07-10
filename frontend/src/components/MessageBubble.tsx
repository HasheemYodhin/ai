import { lazy, Suspense, useMemo, useState, useRef, useEffect, useCallback, type KeyboardEvent } from 'react'
import type { Message } from '@/types'
import { cn } from '@/lib/utils'
import { Bot, User, AlertCircle, Copy, Check, Pencil, RotateCcw, Globe, Loader2, ImageDown, Volume2, VolumeX } from 'lucide-react'
import { speak } from '@/lib/tts'
import { RegenerateMenu } from './RegenerateMenu'
import { DownloadMenu } from './DownloadMenu'

const MarkdownRenderer = lazy(() =>
  import('./MarkdownRenderer').then(mod => ({ default: mod.MarkdownRenderer }))
)

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
  onEdit?: (id: string, content: string) => void
  onRegenerate?: (id: string, overrides?: { model?: string; effort?: string }) => void
}

export function MessageBubble({ message, isStreaming, onEdit, onRegenerate }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isError = message.error
  const [copied, setCopied] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [draft, setDraft] = useState(message.content)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [speakError, setSpeakError] = useState<string | null>(null)
  const [streamElapsed, setStreamElapsed] = useState(0)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const stopSpeakingRef = useRef<(() => void) | null>(null)
  // Guards against re-triggering auto-play on unrelated re-renders — this
  // instance persists across re-renders because the parent list keys on
  // message.id, so the ref only resets when the message itself is new.
  const hasAutoPlayedRef = useRef(false)

  useEffect(() => {
    if (isEditing) {
      textareaRef.current?.focus()
      textareaRef.current?.setSelectionRange(draft.length, draft.length)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing])

  const handleToggleSpeak = useCallback(async () => {
    if (isSpeaking) {
      stopSpeakingRef.current?.()
      setIsSpeaking(false)
      return
    }
    setSpeakError(null)
    setIsSpeaking(true)
    try {
      const controller = await speak(message.content, () => setIsSpeaking(false))
      stopSpeakingRef.current = controller.stop
    } catch (err) {
      setSpeakError((err as Error).message || 'Speech failed')
      setIsSpeaking(false)
    }
  }, [isSpeaking, message.content])

  // Auto-speak replies to a voice-input turn — feels like an actual voice
  // conversation instead of silently reverting to text once you'd spoken.
  useEffect(() => {
    if (!isUser && message.viaVoice && !isStreaming && message.content && !hasAutoPlayedRef.current) {
      hasAutoPlayedRef.current = true
      handleToggleSpeak()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isUser, message.viaVoice, isStreaming, message.content])

  useEffect(() => {
    return () => stopSpeakingRef.current?.()
  }, [])

  useEffect(() => {
    if (!isStreaming) {
      setStreamElapsed(0)
      return
    }
    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      setStreamElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [isStreaming, message.id])

  const timeStr = useMemo(() => {
    if (!message.timestamp) return ''
    return new Date(message.timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
  }, [message.timestamp])

  const handleCopy = async () => {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const startEdit = () => {
    setDraft(message.content)
    setIsEditing(true)
  }

  const submitEdit = () => {
    const trimmed = draft.trim()
    setIsEditing(false)
    if (trimmed && trimmed !== message.content) {
      onEdit?.(message.id, trimmed)
    }
  }

  const handleEditKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submitEdit()
    } else if (e.key === 'Escape') {
      setIsEditing(false)
    }
  }

  return (
    <div
      className={cn(
        'group flex gap-3 w-full animate-fade-in',
        isUser ? 'justify-end' : 'justify-start'
      )}
    >
      {!isUser && (
        <div className="flex-shrink-0 mt-1">
          <div className={cn(
            'w-8 h-8 rounded-lg flex items-center justify-center border',
            isError
              ? 'bg-red-500/10 border-red-500/20 text-red-500'
              : 'bg-accent/10 border-accent/20 text-accent'
          )}>
            {isError ? (
              <AlertCircle className="w-4 h-4" />
            ) : (
              <Bot className="w-4 h-4" />
            )}
          </div>
        </div>
      )}

      <div className={cn(
        'flex flex-col max-w-[85%] md:max-w-[75%]',
        isUser ? 'items-end' : 'items-start'
      )}>
        {isEditing ? (
          <div className="w-full min-w-[280px] rounded-2xl px-3.5 py-3 glass-input">
            <textarea
              ref={textareaRef}
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={handleEditKeyDown}
              rows={Math.min(8, Math.max(2, draft.split('\n').length))}
              className="w-full resize-none bg-transparent text-[15px] leading-relaxed outline-none text-text-primary dark:text-text-dark-primary"
            />
            <div className="flex items-center justify-end gap-2 mt-2">
              <button
                onClick={() => setIsEditing(false)}
                className="text-xs px-3 py-1.5 rounded-lg text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={submitEdit}
                className="text-xs px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-white font-medium transition-colors"
              >
                Save & submit
              </button>
            </div>
          </div>
        ) : (
          <div
            className={cn(
              'rounded-2xl px-4 py-3',
              isUser
                ? 'glass-card-user text-white rounded-br-sm'
                : isError
                  ? 'bg-red-50 dark:bg-red-950/20 border border-red-200/50 dark:border-red-900/50 rounded-bl-sm text-text-primary dark:text-text-dark-primary'
                  : 'glass-card-bot rounded-bl-sm'
            )}
          >
            {isUser ? (
              <div>
                {message.images && message.images.length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-2">
                    {message.images.map((src, i) => (
                      <img
                        key={i}
                        src={src}
                        alt={`attachment ${i + 1}`}
                        className="max-h-40 rounded-lg border border-white/20 object-cover"
                      />
                    ))}
                  </div>
                )}
                {message.content && (
                  <p className="text-[15px] leading-relaxed whitespace-pre-wrap">
                    {message.content}
                  </p>
                )}
                {message.imageMode === 'ocr' && (
                  <span className="mt-1 inline-block text-[10px] text-white/70">
                    text extracted via OCR
                  </span>
                )}
              </div>
            ) : (
              <div className="text-[15px] leading-relaxed text-text-primary dark:text-text-dark-primary">
                {message.agentActivity && message.agentActivity.steps.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {message.agentActivity.steps.map((step, i) => (
                      <span
                        key={i}
                        title={step.detail}
                        className={cn(
                          'inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-full bg-surface-tertiary dark:bg-surface-dark-tertiary',
                          step.success === false ? 'text-red-500' : 'text-text-secondary dark:text-text-dark-secondary'
                        )}
                      >
                        <Globe className="w-3 h-3 text-accent flex-shrink-0" />
                        <span className="font-mono text-[10px] text-accent">{step.tool}</span>
                        {step.detail && <span className="truncate max-w-[160px]">{step.detail}</span>}
                      </span>
                    ))}
                    {!message.agentActivity.done && (
                      <span className="inline-flex items-center gap-1 text-xs px-2 py-1 text-accent">
                        <Loader2 className="w-3 h-3 animate-spin" /> {message.agentActivity.label}…
                      </span>
                    )}
                  </div>
                )}

                {message.isGeneratingImage && (
                  <div className="flex items-center gap-2 text-text-secondary dark:text-text-dark-secondary">
                    <Loader2 className="w-4 h-4 animate-spin text-accent" />
                    Generating image…
                  </div>
                )}

                {message.generatedImages && message.generatedImages.length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-2">
                    {message.generatedImages.map((src, i) => (
                      <div key={i} className="relative group/img">
                        <img src={src} alt={`generated ${i + 1}`} className="max-w-full max-h-80 rounded-lg border border-border dark:border-border-dark" />
                        <a
                          href={src}
                          download={`dabba-image-${i + 1}.png`}
                          className="absolute top-2 right-2 p-1.5 rounded-lg bg-black/50 text-white opacity-0 group-hover/img:opacity-100 transition-opacity"
                          title="Download image"
                        >
                          <ImageDown className="w-4 h-4" />
                        </a>
                      </div>
                    ))}
                  </div>
                )}

                {message.content ? (
                  <Suspense fallback={<div className="text-sm text-text-tertiary dark:text-text-dark-tertiary">Loading message…</div>}>
                    <MarkdownRenderer content={message.content} />
                  </Suspense>
                ) : isStreaming ? (
                  <div className="typing-indicator">
                    <span />
                    <span />
                    <span />
                  </div>
                ) : null}
              </div>
            )}
          </div>
        )}

        <div className={cn(
          'flex items-center gap-1.5 mt-1 px-1 min-h-[22px]',
          isUser ? 'flex-row-reverse' : 'flex-row'
        )}>
          <span className="text-[10px] text-text-tertiary dark:text-text-dark-tertiary font-medium">
            {timeStr}
          </span>
          {isUser && (
            <div className="w-5 h-5 rounded-full bg-accent/15 flex items-center justify-center">
              <User className="w-3 h-3 text-accent" />
            </div>
          )}
          {isStreaming && (
            <span className="text-[10px] text-accent animate-pulse font-medium">
              {streamElapsed >= 20 ? 'Still working...' : 'Generating...'}
            </span>
          )}

          {/* Model + token usage on assistant replies */}
          {!isUser && !isStreaming && !isError && message.model && (
            <span className="text-[10px] text-text-tertiary dark:text-text-dark-tertiary">
              {message.model}
              {message.usage && ` · ${message.usage.totalTokens} tok`}
            </span>
          )}

          {!isEditing && !isStreaming && (message.content || (message.generatedImages?.length ?? 0) > 0) && (
            <div className={cn(
              'flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity',
              isUser ? 'flex-row-reverse' : 'flex-row'
            )}>
              <button
                onClick={handleCopy}
                title="Copy"
                className="p-1 rounded-md text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
              >
                {copied ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
              </button>
              {isUser && onEdit && (
                <button
                  onClick={startEdit}
                  title="Edit"
                  className="p-1 rounded-md text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
                >
                  <Pencil className="w-3 h-3" />
                </button>
              )}
              {/* Errored reply → retry with same model; successful reply → regenerate (with model options) */}
              {!isUser && isError && onRegenerate && (
                <button
                  onClick={() => onRegenerate(message.id)}
                  title="Retry"
                  className="flex items-center gap-1 px-1.5 py-1 rounded-md text-text-tertiary hover:text-accent hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
                >
                  <RotateCcw className="w-3 h-3" />
                  <span className="text-[10px] font-medium">Retry</span>
                </button>
              )}
              {!isUser && !isError && onRegenerate && (
                <RegenerateMenu onRegenerate={(overrides) => onRegenerate(message.id, overrides)} />
              )}
              {!isUser && !isError && message.content && (
                <button
                  onClick={handleToggleSpeak}
                  title={isSpeaking ? 'Stop' : 'Play aloud'}
                  className={cn(
                    'p-1 rounded-md transition-colors',
                    isSpeaking
                      ? 'text-accent'
                      : 'text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
                  )}
                >
                  {isSpeaking ? <VolumeX className="w-3 h-3" /> : <Volume2 className="w-3 h-3" />}
                </button>
              )}
              {!isUser && !isError && message.content && (
                <DownloadMenu content={message.content} baseName={message.content.slice(0, 40) || 'dabba-reply'} />
              )}
            </div>
          )}
          {speakError && (
            <span className="text-[10px] text-red-500">{speakError}</span>
          )}
        </div>
      </div>
    </div>
  )
}
