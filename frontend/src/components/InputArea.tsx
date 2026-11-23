import { useState, useRef, useCallback, useEffect, type KeyboardEvent, type ChangeEvent } from 'react'
import { ArrowUp, Square, X, FileText, Image as ImageIcon, Sparkles, Wand2, Bot, Mic, AudioLines, Loader2, ListChecks } from 'lucide-react'
import { cn } from '@/lib/utils'
import { fileToDataUrl } from '@/lib/ocr'
import { captureScreenshot } from '@/lib/screenshot'
import { startRecording, type VoiceRecorder } from '@/lib/voice'
import { apiClient } from '@/api/client'
import { ConnectorMenuIcon, PlusMenu, type ActiveMode } from './PlusMenu'
import { VoiceRecordingModal } from './VoiceRecordingModal'
import { ModelSwitcher } from './ModelSwitcher'
import { useSkills } from '@/hooks/useSkills'
import type { UploadedFile, Project, ExtractedDocument, DocumentAttachment } from '@/types'

interface InputAreaProps {
  onSend: (content: string, images?: string[], opts?: { systemPromptOverride?: string; viaVoice?: boolean; documents?: ExtractedDocument[]; attachments?: DocumentAttachment[] }) => void
  onRunAgentMode: (content: string, opts: { label: string; effort?: string; hint?: string; allowedTools?: string[]; viaVoice?: boolean; planMode?: boolean }) => void
  onGenerateImage: (prompt: string) => void
  onStop: () => void
  isLoading: boolean
  disabled?: boolean
  placeholder?: string
  projects: Project[]
  currentProjectId?: string | null
  onAddToProject: (projectId: string) => void
  /** Set externally (e.g. sidebar's "Research mode" shortcut) to pre-select a mode on mount. */
  initialMode?: ActiveMode | null
  onInitialModeConsumed?: () => void
}

const MAX_FILES = 5
const MAX_IMAGE_FILE_SIZE = 10 * 1024 * 1024
const MAX_DOCUMENT_FILE_SIZE = 25 * 1024 * 1024
const MAX_ZIP_FILE_SIZE = 100 * 1024 * 1024

function isZipFile(file: File): boolean {
  return file.type === 'application/zip'
    || file.type === 'application/x-zip-compressed'
    || file.name.toLowerCase().endsWith('.zip')
}

function attachmentLimit(file: File): number {
  if (isZipFile(file)) return MAX_ZIP_FILE_SIZE
  if (file.type.startsWith('image/')) return MAX_IMAGE_FILE_SIZE
  return MAX_DOCUMENT_FILE_SIZE
}

function attachmentLimitLabel(file: File): string {
  if (isZipFile(file)) return '100 MiB ZIP attachment limit'
  if (file.type.startsWith('image/')) return '10 MB image attachment limit'
  return '25 MiB document attachment limit'
}

export function InputArea({
  onSend,
  onRunAgentMode,
  onGenerateImage,
  onStop,
  isLoading,
  disabled = false,
  placeholder = 'Ask anything…',
  projects,
  currentProjectId,
  onAddToProject,
  initialMode,
  onInitialModeConsumed,
}: InputAreaProps) {
  const [value, setValue] = useState('')
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [fileError, setFileError] = useState<string | null>(null)
  const [mode, setMode] = useState<ActiveMode>({ kind: 'chat' })
  // When on, a multi-step agent turn must be approved before it executes
  // instead of running immediately (see AgentConfig.require_plan_approval).
  // Only meaningful in agent mode; harmless to leave set when switching modes.
  const [planModeEnabled, setPlanModeEnabled] = useState(false)
  const [isQuickRecording, setIsQuickRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [isExtractingDocuments, setIsExtractingDocuments] = useState(false)
  const [voiceModalOpen, setVoiceModalOpen] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const quickRecorderRef = useRef<VoiceRecorder | null>(null)
  // Set whenever text comes in via mic/voice-mode — tells the reply to speak
  // itself back automatically. Cleared once the message is actually sent.
  const [pendingViaVoice, setPendingViaVoice] = useState(false)
  const { skills } = useSkills()

  const insertTranscript = useCallback((text: string) => {
    setValue(prev => (prev.trim() ? `${prev.trim()} ${text}` : text))
    setPendingViaVoice(true)
    textareaRef.current?.focus()
  }, [])

  const handleMicClick = useCallback(async () => {
    if (isQuickRecording) {
      // Second click: stop recording and transcribe what was captured.
      const recorder = quickRecorderRef.current
      quickRecorderRef.current = null
      setIsQuickRecording(false)
      if (!recorder) return
      setIsTranscribing(true)
      try {
        const blob = await recorder.stop()
        const text = await apiClient.transcribeAudio(blob)
        if (text) insertTranscript(text)
      } catch (err) {
        setVoiceError((err as Error).message || 'Transcription failed')
      } finally {
        setIsTranscribing(false)
      }
      return
    }

    setVoiceError(null)
    try {
      quickRecorderRef.current = await startRecording()
      setIsQuickRecording(true)
    } catch (err) {
      setVoiceError((err as Error).message || 'Could not access the microphone')
    }
  }, [isQuickRecording, insertTranscript])

  useEffect(() => {
    if (initialMode) {
      setMode(initialMode)
      onInitialModeConsumed?.()
    }
  }, [initialMode, onInitialModeConsumed])

  const adjustHeight = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = '0'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [])

  useEffect(() => {
    adjustHeight()
  }, [value, adjustHeight])

  const handleFiles = useCallback(async (fileList: FileList) => {
    setFileError(null)
    const remaining = MAX_FILES - files.length
    const toProcess = Array.from(fileList).slice(0, remaining)

    const accepted = toProcess.filter(f => {
      if (f.size > attachmentLimit(f)) {
        setFileError(`"${f.name}" exceeds the ${attachmentLimitLabel(f)}`)
        return false
      }
      return true
    })

    // Only small images are base64 encoded. Documents and ZIP files
    // retain their browser File handle and are streamed as multipart uploads.
    const next: UploadedFile[] = await Promise.all(
      accepted.map(async f => {
        if (f.type.startsWith('image/')) {
          const dataUrl = await fileToDataUrl(f)
          return {
            id: crypto.randomUUID(),
            name: f.name,
            size: f.size,
            type: f.type,
            file: f,
            dataUrl,
            preview: dataUrl,
          }
        }
        return {
          id: crypto.randomUUID(),
          name: f.name,
          size: f.size,
          type: f.type,
          file: f,
        }
      })
    )

    if (toProcess.length < fileList.length) {
      setFileError(`Maximum ${MAX_FILES} files allowed`)
    }
    setFiles(prev => [...prev, ...next])
  }, [files.length])

  const handleScreenshot = useCallback(async () => {
    setFileError(null)
    try {
      const dataUrl = await captureScreenshot()
      setFiles(prev => [...prev, {
        id: crypto.randomUUID(),
        name: `screenshot-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.png`,
        size: Math.round(dataUrl.length * 0.75), // rough decoded-size estimate from base64 length
        type: 'image/png',
        dataUrl,
        preview: dataUrl,
      }])
    } catch (err) {
      setFileError((err as Error).message || 'Screenshot capture was cancelled or failed')
    }
  }, [])

  const removeFile = useCallback((id: string) => {
    setFiles(prev => prev.filter(f => f.id !== id))
  }, [])

  const handleFileInputChange = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(e.target.files)
    }
    e.target.value = ''
  }, [handleFiles])

  const handleSend = useCallback(async () => {
    const trimmed = value.trim()
    if ((!trimmed && files.length === 0) || isLoading || isExtractingDocuments || disabled) return

    if (mode.kind === 'agent') {
      onRunAgentMode(trimmed, { label: mode.label, effort: mode.effort, hint: mode.hint, allowedTools: mode.allowedTools, viaVoice: pendingViaVoice, planMode: planModeEnabled })
    } else if (mode.kind === 'image') {
      onGenerateImage(trimmed)
    } else {
      const imageFiles = files.filter(f => f.type.startsWith('image/') && f.dataUrl)
      const images = imageFiles.map(f => f.dataUrl as string)

      const otherFiles = files.filter(f => !f.type.startsWith('image/'))
      let documents: ExtractedDocument[] | undefined
      if (otherFiles.length > 0) {
        setIsExtractingDocuments(true)
        setFileError(null)
        try {
          documents = await apiClient.extractDocuments(otherFiles)
        } catch (err) {
          setFileError((err as Error).message || 'Could not read the attached document')
          setIsExtractingDocuments(false)
          return
        }
        setIsExtractingDocuments(false)
      }
      const systemPromptOverride = mode.kind === 'skill'
        ? skills.find(s => s.id === mode.skillId)?.instructions
        : undefined

      onSend(trimmed, images.length ? images : undefined, {
        systemPromptOverride,
        viaVoice: pendingViaVoice,
        documents,
        attachments: otherFiles.map(file => ({
          name: file.name,
          size: file.size,
          type: file.type,
          dataUrl: file.dataUrl,
        })),
      })
    }

    setValue('')
    setFiles([])
    setPendingViaVoice(false)
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }, [value, files, isLoading, isExtractingDocuments, disabled, mode, onSend, onRunAgentMode, onGenerateImage, skills, pendingViaVoice, planModeEnabled])

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    // IME keyboards emit Enter while composing; never submit partial text.
    if (e.nativeEvent.isComposing) return
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSend()
    }
  }, [handleSend])

  const handleChange = useCallback((e: ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
  }, [])

  const charCount = value.length
  const maxChars = 50000
  const isNearLimit = charCount > maxChars * 0.9
  const isOverLimit = charCount > maxChars

  const connectorName = mode.kind === 'agent' && mode.label.startsWith('Connector: ')
    ? mode.label.slice('Connector: '.length).trim()
    : null
  const modeChip = mode.kind === 'image'
    ? { icon: Wand2, label: 'Create an image', placeholder: 'Describe the image to generate…' }
    : mode.kind === 'agent'
      ? { icon: Bot, label: mode.label, placeholder: connectorName ? `Ask ${connectorName}…` : `${mode.label}…` }
      : mode.kind === 'skill'
        ? { icon: Sparkles, label: mode.name, placeholder }
        : null
  const effectivePlaceholder = modeChip?.placeholder ?? placeholder

  return (
    <div className="bg-transparent">
      <div className="max-w-3xl mx-auto px-4 pt-2 pb-4">
        {modeChip && (
          <div className="flex items-center gap-1.5 mb-2">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent/10 text-accent text-xs font-medium">
              {connectorName
                ? <ConnectorMenuIcon name={connectorName} compact />
                : <modeChip.icon className="w-3.5 h-3.5" />}
              {modeChip.label}
              <button onClick={() => setMode({ kind: 'chat' })} className="ml-0.5 hover:text-accent-hover">
                <X className="w-3 h-3" />
              </button>
            </span>
            {mode.kind === 'agent' && (
              <button
                type="button"
                onClick={() => setPlanModeEnabled(v => !v)}
                title="Propose a plan and wait for your approval before it runs"
                className={cn(
                  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors',
                  planModeEnabled
                    ? 'bg-accent text-white'
                    : 'bg-surface-tertiary text-text-tertiary hover:text-text-secondary dark:bg-surface-dark-tertiary dark:hover:text-text-dark-secondary'
                )}
              >
                <ListChecks className="w-3.5 h-3.5" />
                Plan mode
              </button>
            )}
          </div>
        )}

        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-2">
            {files.map(file => (
              <div
                key={file.id}
                className="flex items-center gap-2 pl-2 pr-1 py-1.5 rounded-lg bg-surface-tertiary dark:bg-surface-dark-tertiary text-sm"
              >
                {file.preview ? (
                  <img src={file.preview} alt="" className="w-6 h-6 rounded object-cover" />
                ) : file.type.startsWith('image/') ? (
                  <ImageIcon className="w-4 h-4 text-accent" />
                ) : (
                  <FileText className="w-4 h-4 text-accent" />
                )}
                <span className="text-text-primary dark:text-text-dark-primary truncate max-w-[140px]">
                  {file.name}
                </span>
                <button
                  type="button"
                  onClick={() => removeFile(file.id)}
                  aria-label={`Remove ${file.name}`}
                  className="p-1 rounded hover:bg-surface dark:hover:bg-surface-dark text-text-tertiary hover:text-red-500 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        {fileError && (
          <p className="text-xs text-red-500 mb-2">{fileError}</p>
        )}

        {voiceError && (
          <p className="text-xs text-red-500 mb-2">{voiceError}</p>
        )}

        <div className="composer relative flex flex-col rounded-3xl transition-colors focus-within:border-accent/40">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,.zip,.pdf,.docx,.xlsx,.pptx,.txt,.md,.markdown,.json,.jsonl,.csv"
            className="hidden"
            onChange={handleFileInputChange}
          />

          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder={effectivePlaceholder}
            aria-label={effectivePlaceholder}
            rows={1}
            disabled={disabled}
            maxLength={maxChars + 100}
            className={cn(
              'w-full resize-none bg-transparent px-5 pt-4 pb-2 text-base leading-7 outline-none',
              'text-text-primary dark:text-text-dark-primary',
              'placeholder:text-text-tertiary dark:placeholder:text-text-dark-tertiary',
              'disabled:opacity-50 scrollbar-thin'
            )}
          />

          <div className="flex items-center gap-1 px-2.5 pb-2.5">
          <PlusMenu
            disabled={isLoading || isExtractingDocuments || disabled}
            mode={mode}
            onModeChange={setMode}
            onAttachFiles={() => fileInputRef.current?.click()}
            onScreenshot={handleScreenshot}
            projects={projects}
            currentProjectId={currentProjectId}
            onAddToProject={onAddToProject}
          />

          {connectorName && (
            <span className="self-center" title={`${connectorName} connector`}>
              <ConnectorMenuIcon name={connectorName} compact />
            </span>
          )}

          <div className="flex-1" />
          <ModelSwitcher placement="up" />
            <button
              type="button"
              onClick={handleMicClick}
              disabled={isLoading || isExtractingDocuments || disabled || isTranscribing}
              title={isQuickRecording ? 'Stop and transcribe' : 'Voice input'}
              aria-label={isQuickRecording ? 'Stop recording and transcribe' : 'Start voice input'}
              className={cn(
                'w-9 h-9 flex items-center justify-center rounded-full transition-colors disabled:opacity-40',
                isQuickRecording
                  ? 'bg-red-500 hover:bg-red-600 text-white'
                  : 'text-text-tertiary hover:text-text-primary dark:text-text-dark-tertiary dark:hover:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
              )}
            >
              {isTranscribing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mic className="w-4 h-4" />}
            </button>
            <button
              type="button"
              onClick={() => setVoiceModalOpen(true)}
              disabled={isLoading || isExtractingDocuments || disabled}
              title="Voice mode"
              aria-label="Open voice mode"
              className="w-9 h-9 flex items-center justify-center rounded-full text-text-tertiary hover:text-text-primary dark:text-text-dark-tertiary dark:hover:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors disabled:opacity-40"
            >
              <AudioLines className="w-4 h-4" />
            </button>
            {isLoading ? (
              <button
                type="button"
                onClick={onStop}
                className="ml-1 w-9 h-9 flex items-center justify-center rounded-full bg-text-primary dark:bg-text-dark-primary text-surface dark:text-surface-dark hover:opacity-90 active:scale-[0.97] transition-[opacity,transform]"
                title="Stop generation"
                aria-label="Stop generation"
              >
                <Square className="w-3.5 h-3.5 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void handleSend()}
                disabled={(!value.trim() && files.length === 0) || isExtractingDocuments || disabled}
                className={cn(
                  'ml-1 w-9 h-9 flex items-center justify-center rounded-full transition-[background-color,transform]',
                  (value.trim() || files.length > 0)
                    ? 'bg-accent hover:bg-accent-hover text-white active:scale-[0.97]'
                    : 'bg-surface-tertiary dark:bg-surface-dark-secondary text-text-tertiary dark:text-text-dark-tertiary cursor-not-allowed'
                )}
                title="Send message"
                aria-label="Send message"
              >
                {isExtractingDocuments
                  ? <Loader2 className="w-4 h-4 animate-spin" />
                  : <ArrowUp className="w-5 h-5" strokeWidth={2} />}
              </button>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between mt-2 px-1">
          <div className="flex items-center gap-1 text-xs text-text-tertiary dark:text-text-dark-tertiary">
            <kbd className="px-1 rounded border border-border dark:border-border-dark font-mono text-[11px] leading-4">Enter</kbd>
            <span className="mr-2">send</span>
            <kbd className="px-1 rounded border border-border dark:border-border-dark font-mono text-[11px] leading-4">Shift</kbd>
            <kbd className="px-1 rounded border border-border dark:border-border-dark font-mono text-[11px] leading-4">Enter</kbd>
            <span>new line</span>
          </div>
          {charCount > 0 && (
            <span className={cn(
              'text-xs font-mono tabular-nums text-text-tertiary dark:text-text-dark-tertiary',
              isOverLimit && 'text-red-500',
              isNearLimit && !isOverLimit && 'text-amber-500',
            )}>
              {isNearLimit ? `${charCount}/${maxChars} characters` : `~${Math.ceil(charCount / 4)} tokens`}
            </span>
          )}
        </div>
      </div>

      {voiceModalOpen && (
        <VoiceRecordingModal
          onClose={() => setVoiceModalOpen(false)}
          onTranscribed={insertTranscript}
        />
      )}
    </div>
  )
}
