import { lazy, Suspense, useMemo, useState, useRef, useEffect, useCallback, type KeyboardEvent } from 'react'
import type { Message } from '@/types'
import { cn } from '@/lib/utils'
import { User, AlertCircle, Copy, Check, Pencil, RotateCcw, Globe, Loader2, ImageDown, Volume2, VolumeX, FileText, FileSpreadsheet, Presentation, Download } from 'lucide-react'
import { speak } from '@/lib/tts'
import { RegenerateMenu } from './RegenerateMenu'
import { DownloadMenu } from './DownloadMenu'
import logo from '../icon.svg'

const MarkdownRenderer = lazy(() =>
  import('./MarkdownRenderer').then(mod => ({ default: mod.MarkdownRenderer }))
)

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
  onEdit?: (id: string, content: string) => void
  onRegenerate?: (id: string, overrides?: { model?: string; effort?: string }) => void
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
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
  const isActing = !isUser && !isError && (
    !!isStreaming
    || !!message.isGeneratingImage
    || (!!message.agentActivity && !message.agentActivity.done)
  )

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
          <div className="relative w-8 h-8" aria-label="Dabba">
            <div className={cn(
              'relative z-10 w-8 h-8 rounded-lg flex items-center justify-center border transition-colors',
              isError
                ? 'bg-red-500/10 border-red-500/20 text-red-500'
                : 'bg-accent/10 border-accent/20 text-accent'
            )}>
              {isError ? (
                <AlertCircle className="w-4 h-4" />
              ) : (
                <img
                  src={logo}
                  alt="Dabba"
                  className={cn(
                    'w-5 h-5 object-contain',
                    isActing && 'animate-spin'
                  )}
                />
              )}
            </div>
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
                {message.documentAttachments && message.documentAttachments.length > 0 && (
                  <div className={cn(
                    'grid gap-2',
                    message.content && 'mb-2',
                    message.documentAttachments.length > 1
                      ? 'sm:grid-cols-2'
                      : 'grid-cols-1'
                  )}>
                    {message.documentAttachments.map((attachment, index) => {
                      const isPdf = attachment.type === 'application/pdf'
                        || attachment.name.toLowerCase().endsWith('.pdf')
                      const extension = attachment.name.split('.').pop()?.toUpperCase() || 'FILE'

                      return (
                        <div
                          key={`${attachment.name}-${index}`}
                          className="w-[250px] max-w-full overflow-hidden rounded-xl border border-white/30 bg-white/95 text-left text-slate-900 shadow-sm"
                        >
                          {isPdf && attachment.dataUrl ? (
                            <div className="relative h-32 overflow-hidden bg-slate-100">
                              <object
                                data={`${attachment.dataUrl}#page=1&toolbar=0&navpanes=0&scrollbar=0`}
                                type="application/pdf"
                                aria-label={`Preview of ${attachment.name}`}
                                className="h-full w-full pointer-events-none"
                              >
                                <div className="flex h-full items-center justify-center">
                                  <FileText className="h-12 w-12 text-red-500" />
                                </div>
                              </object>
                              <span className="absolute left-2 top-2 rounded-md bg-red-600 px-1.5 py-0.5 text-[9px] font-bold tracking-wide text-white shadow-sm">
                                PDF
                              </span>
                            </div>
                          ) : (
                            <div className="flex h-24 items-center justify-center bg-slate-100">
                              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-100 text-blue-600">
                                <FileText className="h-6 w-6" />
                              </div>
                            </div>
                          )}
                          <div className="flex items-center gap-2.5 px-3 py-2.5">
                            <div className={cn(
                              'flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-[9px] font-bold text-white',
                              isPdf ? 'bg-red-600' : 'bg-blue-600'
                            )}>
                              {isPdf ? 'PDF' : extension.slice(0, 4)}
                            </div>
                            <div className="min-w-0">
                              <p className="truncate text-xs font-semibold" title={attachment.name}>
                                {attachment.name}
                              </p>
                              <p className="mt-0.5 text-[10px] text-slate-500">
                                {formatFileSize(attachment.size)}
                              </p>
                            </div>
                          </div>
                        </div>
                      )
                    })}
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
                  <div className="flex flex-col gap-1 mb-2">
                    {message.agentActivity.steps.map((step, i) => (
                      <div
                        key={i}
                        title={step.detail}
                        className={cn(
                          'flex items-center gap-1.5 text-xs',
                          step.success === false ? 'text-red-500' : 'text-text-secondary dark:text-text-dark-secondary'
                        )}
                      >
                        <img
                          src={logo}
                          alt="Dabba"
                          className={cn(
                            'w-3.5 h-3.5 object-contain flex-shrink-0',
                            step.success === undefined && !message.agentActivity?.done && 'animate-spin'
                          )}
                        />
                        <span className="font-mono text-[10px] text-accent">{step.tool}</span>
                        {step.detail && <span className="truncate max-w-[160px]">{step.detail}</span>}
                      </div>
                    ))}
                    {!message.agentActivity.done && (
                      <div className="flex items-center gap-1.5 text-xs text-accent">
                        <img src={logo} alt="Dabba" className="w-3.5 h-3.5 object-contain flex-shrink-0 animate-spin" />
                        <span>{message.agentActivity.label}…</span>
                      </div>
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

                {message.generatedFiles && message.generatedFiles.length > 0 && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {message.generatedFiles.map((file, index) => {
                      const extension = file.name.split('.').pop()?.toUpperCase() || 'FILE'
                      const isPdf = file.type === 'application/pdf'
                      const isExcel = file.type.includes('spreadsheet')
                      const isPowerPoint = file.type.includes('presentation')
                      const Icon = isExcel
                        ? FileSpreadsheet
                        : isPowerPoint
                          ? Presentation
                          : FileText
                      const accentClass = isPdf
                        ? 'bg-red-500/10 text-red-600 dark:text-red-400'
                        : isExcel
                          ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                          : isPowerPoint
                            ? 'bg-orange-500/10 text-orange-600 dark:text-orange-400'
                            : 'bg-blue-500/10 text-blue-600 dark:text-blue-400'

                      return (
                        <a
                          key={`${file.name}-${index}`}
                          href={file.dataUrl}
                          download={file.name}
                          className="group/file flex min-w-0 items-center gap-3 rounded-xl border border-border bg-surface-secondary p-3 transition-colors hover:border-accent/40 hover:bg-surface-tertiary dark:border-border-dark dark:bg-surface-dark-tertiary dark:hover:bg-surface-dark-secondary"
                          title={`Download ${file.name}`}
                        >
                          <div className={cn('flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl', accentClass)}>
                            <Icon className="h-5 w-5" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-xs font-semibold text-text-primary dark:text-text-dark-primary">
                              {file.name}
                            </p>
                            <p className="mt-0.5 text-[10px] text-text-tertiary dark:text-text-dark-tertiary">
                              {extension} · {formatFileSize(file.size)}
                            </p>
                          </div>
                          <Download className="h-4 w-4 flex-shrink-0 text-text-tertiary transition-colors group-hover/file:text-accent" />
                        </a>
                      )
                    })}
                  </div>
                )}
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
