import { lazy, memo, Suspense, useMemo, useState, useRef, useEffect, useCallback, type KeyboardEvent } from 'react'
import { modelDisplayName } from '@/lib/models'
import type { Message } from '@/types'
import { cn } from '@/lib/utils'
import { AlertCircle, ChevronRight, X, Copy, Check, Pencil, RotateCcw, Loader2, ImageDown, Volume2, VolumeX, FileText, FileSpreadsheet, Presentation, Download } from 'lucide-react'
import { speak } from '@/lib/tts'
import { useSettings } from '@/hooks/useSettings'
import { useSmoothText } from '@/hooks/useSmoothText'
import { loadMarkdownRenderer } from '@/lib/markdownRenderer'
import { RegenerateMenu } from './RegenerateMenu'
import { DownloadMenu } from './DownloadMenu'
import logo from '../icon.svg'

const MarkdownRenderer = lazy(loadMarkdownRenderer)

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
  onRevealChange?: (id: string, revealing: boolean) => void
  onEdit?: (id: string, content: string) => void
  onRegenerate?: (id: string, overrides?: { model?: string; effort?: string }) => void
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export const MessageBubble = memo(function MessageBubble({ message, isStreaming, onRevealChange, onEdit, onRegenerate }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isError = message.error
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [stepsOpen, setStepsOpen] = useState(false)
  const { text: shownContent, revealing } = useSmoothText(message.content, !!isStreaming && message.role !== 'user')
  const writing = !!isStreaming || revealing
  useEffect(() => {
    onRevealChange?.(message.id, writing)
  }, [message.id, onRevealChange, writing])
  const [draft, setDraft] = useState(message.content)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [speakError, setSpeakError] = useState<string | null>(null)
  const [streamElapsed, setStreamElapsed] = useState(0)
  const { settings } = useSettings()
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
    setCopyError(null)
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(message.content)
      } else {
        const helper = document.createElement('textarea')
        helper.value = message.content
        helper.style.position = 'fixed'
        helper.style.opacity = '0'
        document.body.appendChild(helper)
        try {
          helper.select()
          if (!document.execCommand('copy')) throw new Error('Copy was not permitted')
        } finally {
          helper.remove()
        }
      }
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch (err) {
      setCopyError((err as Error).message || 'Could not copy message')
    }
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
      title={timeStr}
      className={cn(
        'group flex gap-4 w-full animate-fade-in',
        isUser ? 'justify-end' : 'justify-start'
      )}
    >
      {!isUser && (
        <div className="flex-shrink-0 pt-1" aria-label="Dabba">
          {isError ? (
            <AlertCircle className="w-6 h-6 text-red-500" strokeWidth={1.5} />
          ) : (
            <img
              src={logo}
              alt="Dabba"
              className={cn('w-6 h-6 object-contain', isActing && 'animate-spin')}
            />
          )}
        </div>
      )}

      <div className={cn(
        'flex flex-col min-w-0',
        isUser ? 'items-end max-w-[85%] md:max-w-[75%]' : 'items-start flex-1'
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
              isUser
                ? 'glass-card-user rounded-3xl px-5 py-3'
                : isError
                  ? 'w-full rounded-xl px-4 py-3 bg-red-50 dark:bg-red-950/20 border border-red-200/50 dark:border-red-900/50 text-text-primary dark:text-text-dark-primary'
                  : 'w-full pt-0.5'
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
                              <span className="absolute left-2 top-2 rounded-md bg-red-600 px-1.5 py-0.5 text-[11px] font-medium text-white">
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
                              'flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-[11px] font-medium text-white',
                              isPdf ? 'bg-red-600' : 'bg-blue-600'
                            )}>
                              {isPdf ? 'PDF' : extension.slice(0, 4)}
                            </div>
                            <div className="min-w-0">
                              <p className="truncate text-xs font-semibold" title={attachment.name}>
                                {attachment.name}
                              </p>
                              <p className="mt-0.5 text-xs text-slate-500">
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
                  <span className="mt-1 inline-block text-xs text-text-tertiary dark:text-text-dark-tertiary">
                    text extracted via OCR
                  </span>
                )}
              </div>
            ) : (
              <div className="text-base leading-7 text-text-primary dark:text-text-dark-primary">
                {message.agentActivity && message.agentActivity.steps.length > 0 && (() => {
                  const activity = message.agentActivity
                  const open = stepsOpen || !activity.done
                  const failed = activity.steps.filter(s => s.success === false).length
                  return (
                    <div className="mb-4">
                      <button
                        type="button"
                        onClick={() => setStepsOpen(o => !o)}
                        disabled={!activity.done}
                        aria-expanded={open}
                        className="flex items-center gap-2 h-8 -ml-1 px-1 rounded-lg text-[13px] text-text-secondary dark:text-text-dark-secondary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors disabled:cursor-default"
                      >
                        {activity.done
                          ? <ChevronRight className={cn('w-4 h-4 transition-transform', open && 'rotate-90')} strokeWidth={1.5} />
                          : <Loader2 className="w-4 h-4 animate-spin text-accent" strokeWidth={1.5} />}
                        <span>
                          {activity.done
                            ? `Used ${activity.steps.length} tool${activity.steps.length === 1 ? '' : 's'}`
                            : `${activity.label}…`}
                        </span>
                        {failed > 0 && <span className="text-xs text-red-600 dark:text-red-400">{failed} failed</span>}
                      </button>
                      {open && (
                        <ol className="mt-1 ml-[7px] pl-4 border-l border-border dark:border-border-dark space-y-1.5">
                          {activity.steps.map((step, i) => {
                            const running = step.success === undefined && !activity.done
                            return (
                              <li key={i} title={step.detail} className="relative flex items-center gap-2 text-[13px] min-w-0">
                                <span className="absolute -left-[21px] flex items-center justify-center w-2.5 h-2.5 rounded-full bg-surface dark:bg-surface-dark">
                                  <span className={cn(
                                    'w-1.5 h-1.5 rounded-full',
                                    step.success === false ? 'bg-red-500' : running ? 'bg-accent animate-pulse' : 'bg-text-tertiary/60 dark:bg-text-dark-tertiary/60'
                                  )} />
                                </span>
                                <span className="font-mono text-xs text-text-primary dark:text-text-dark-primary flex-shrink-0">{step.tool}</span>
                                {step.detail && (
                                  <span className="truncate text-text-tertiary dark:text-text-dark-tertiary">{step.detail}</span>
                                )}
                                {step.success === false && <X className="w-3.5 h-3.5 text-red-500 flex-shrink-0" strokeWidth={1.5} />}
                              </li>
                            )
                          })}
                        </ol>
                      )}
                    </div>
                  )
                })()}

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
                          aria-label={`Download image ${i + 1}`}
                        >
                          <ImageDown className="w-4 h-4" />
                        </a>
                      </div>
                    ))}
                  </div>
                )}

                {message.reasoning && (
                  // The expanded text floats over the reply (absolute, scrollable)
                  // instead of pushing the table/code below down ~280px, which
                  // made clicks land on the wrong element.
                  <details className="relative mb-2 rounded-lg border border-border px-3 py-2 text-sm text-text-secondary dark:border-border-dark dark:text-text-dark-secondary">
                    <summary className="cursor-pointer">Thinking</summary>
                    <p className="absolute left-0 right-0 top-full z-20 mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-surface p-3 shadow-lg dark:border-border-dark dark:bg-surface-dark-secondary">{message.reasoning}</p>
                  </details>
                )}

                {shownContent ? (
                  <Suspense fallback={<p className="whitespace-pre-wrap">{shownContent}</p>}>
                    <MarkdownRenderer content={shownContent} className={writing ? 'streaming-cursor' : undefined} />
                  </Suspense>
                ) : isStreaming && !message.isGeneratingImage ? (
                  <div className="flex items-center gap-3 h-7 text-text-primary dark:text-text-dark-primary" role="status" aria-label="Dabba is thinking">
                    <span className="thinking-dot" />
                    {streamElapsed >= 6 && (
                      <span className="text-[13px] text-text-tertiary dark:text-text-dark-tertiary">
                        {streamElapsed >= 20 ? 'Still waiting for the model' : 'Waiting for the model'} · {streamElapsed}s
                      </span>
                    )}
                  </div>
                ) : null}

                {!shownContent && isStreaming && !message.isGeneratingImage && streamElapsed >= 15 ? (
                  <p className="mt-1 max-w-md text-xs text-text-tertiary dark:text-text-dark-tertiary">
                    {['high', 'xhigh', 'max'].includes(settings.effort)
                      ? 'High reasoning effort makes large models slower to start. Medium effort is much quicker for everyday questions.'
                      : 'Large models can be slow to start when they are busy. A smaller model usually replies faster.'}
                  </p>
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
                            <p className="mt-0.5 text-xs text-text-tertiary dark:text-text-dark-tertiary">
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
          'flex items-center gap-2 mt-1 min-h-8 [&_svg]:w-4 [&_svg]:h-4 [&_svg]:stroke-[1.5]',
          isUser ? 'flex-row-reverse' : 'flex-row -ml-1.5'
        )}>

          {/* Model + token usage on assistant replies */}
          {!isUser && !writing && !isError && message.model && (
            <span className="text-xs text-text-tertiary dark:text-text-dark-tertiary">
              {modelDisplayName(message.model)}
              {message.usage && ` · ${message.usage.totalTokens} tok`}
            </span>
          )}

          {!isEditing && !writing && (message.content || (message.generatedImages?.length ?? 0) > 0) && (
            <div className={cn(
              'flex items-center gap-0.5 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity',
              isUser ? 'flex-row-reverse' : 'flex-row'
            )}>
              <button
                onClick={handleCopy}
                title={copied ? 'Copied' : 'Copy'}
                aria-label={copied ? 'Copied' : 'Copy message'}
                className="p-1.5 rounded-lg text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
              >
                {copied ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
              </button>
              {isUser && onEdit && (
                <button
                  onClick={startEdit}
                  title="Edit"
                  aria-label="Edit message"
                  className="p-1.5 rounded-lg text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
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
                  <span className="text-xs font-medium">Retry</span>
                </button>
              )}
              {!isUser && !isError && onRegenerate && (
                <RegenerateMenu onRegenerate={(overrides) => onRegenerate(message.id, overrides)} />
              )}
              {!isUser && !isError && message.content && (
                <button
                  onClick={handleToggleSpeak}
                  title={isSpeaking ? 'Stop' : 'Play aloud'}
                  aria-label={isSpeaking ? 'Stop reading aloud' : 'Read reply aloud'}
                  className={cn(
                    'p-1.5 rounded-lg transition-colors',
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
            <span className="text-xs text-red-500">{speakError}</span>
          )}
          {copyError && (
            <span role="status" className="text-xs text-red-500">{copyError}</span>
          )}
        </div>
      </div>
    </div>
  )
})
