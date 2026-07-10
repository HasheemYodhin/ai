import { useState, useRef, useCallback, useEffect, type KeyboardEvent, type ChangeEvent } from 'react'
import { Send, Square, X, FileText, Image as ImageIcon, Sparkles, Wand2, Bot, Mic, AudioLines, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { fileToDataUrl } from '@/lib/ocr'
import { captureScreenshot } from '@/lib/screenshot'
import { startRecording, type VoiceRecorder } from '@/lib/voice'
import { apiClient } from '@/api/client'
import { PlusMenu, type ActiveMode } from './PlusMenu'
import { VoiceRecordingModal } from './VoiceRecordingModal'
import { useSkills } from '@/hooks/useSkills'
import type { UploadedFile, Project } from '@/types'

interface InputAreaProps {
  onSend: (content: string, images?: string[], opts?: { systemPromptOverride?: string; viaVoice?: boolean }) => void
  onRunAgentMode: (content: string, opts: { label: string; effort?: string; hint?: string; viaVoice?: boolean }) => void
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
const MAX_FILE_SIZE = 10 * 1024 * 1024

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
  const [isQuickRecording, setIsQuickRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
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
      if (f.size > MAX_FILE_SIZE) {
        setFileError(`"${f.name}" exceeds the 10 MB limit`)
        return false
      }
      return true
    })

    // Read every file to a base64 data URL up-front so send stays synchronous
    // and images survive serialization (object URLs don't).
    const next: UploadedFile[] = await Promise.all(
      accepted.map(async f => ({
        id: crypto.randomUUID(),
        name: f.name,
        size: f.size,
        type: f.type,
        dataUrl: await fileToDataUrl(f),
        preview: f.type.startsWith('image/') ? await fileToDataUrl(f) : undefined,
      }))
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

  const handleSend = useCallback(() => {
    const trimmed = value.trim()
    if ((!trimmed && files.length === 0) || isLoading || disabled) return

    if (mode.kind === 'agent') {
      onRunAgentMode(trimmed, { label: mode.label, effort: mode.effort, hint: mode.hint, viaVoice: pendingViaVoice })
    } else if (mode.kind === 'image') {
      onGenerateImage(trimmed)
    } else {
      const imageFiles = files.filter(f => f.type.startsWith('image/') && f.dataUrl)
      const images = imageFiles.map(f => f.dataUrl as string)

      // Non-image attachments (pdf, txt, …) aren't read yet — note them by name.
      const otherFiles = files.filter(f => !f.type.startsWith('image/'))
      const note = otherFiles.length > 0
        ? `\n\n[Attached: ${otherFiles.map(f => f.name).join(', ')}]`
        : ''

      const systemPromptOverride = mode.kind === 'skill'
        ? skills.find(s => s.id === mode.skillId)?.instructions
        : undefined

      onSend(trimmed + note, images.length ? images : undefined, { systemPromptOverride, viaVoice: pendingViaVoice })
    }

    setValue('')
    setFiles([])
    setPendingViaVoice(false)
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }, [value, files, isLoading, disabled, mode, onSend, onRunAgentMode, onGenerateImage, skills])

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  const handleChange = useCallback((e: ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
  }, [])

  const charCount = value.length
  const maxChars = 50000
  const isNearLimit = charCount > maxChars * 0.9
  const isOverLimit = charCount > maxChars

  const modeChip = mode.kind === 'image'
    ? { icon: Wand2, label: 'Create an image', placeholder: 'Describe the image to generate…' }
    : mode.kind === 'agent'
      ? { icon: Bot, label: mode.label, placeholder: `${mode.label}…` }
      : mode.kind === 'skill'
        ? { icon: Sparkles, label: mode.name, placeholder }
        : null
  const effectivePlaceholder = modeChip?.placeholder ?? placeholder

  return (
    <div className="bg-transparent border-t border-border dark:border-border-dark">
      <div className="max-w-4xl mx-auto px-4 py-4">
        {modeChip && (
          <div className="flex items-center gap-1.5 mb-2">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent/10 text-accent text-xs font-medium">
              <modeChip.icon className="w-3.5 h-3.5" />
              {modeChip.label}
              <button onClick={() => setMode({ kind: 'chat' })} className="ml-0.5 hover:text-accent-hover">
                <X className="w-3 h-3" />
              </button>
            </span>
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
                  onClick={() => removeFile(file.id)}
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

        <div className={cn(
          'relative flex items-end gap-2 rounded-2xl transition-colors',
          'glass-input',
          'focus-within:border-accent/50',
        )}>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handleFileInputChange}
          />
          <PlusMenu
            disabled={isLoading || disabled}
            mode={mode}
            onModeChange={setMode}
            onAttachFiles={() => fileInputRef.current?.click()}
            onScreenshot={handleScreenshot}
            projects={projects}
            currentProjectId={currentProjectId}
            onAddToProject={onAddToProject}
          />

          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder={effectivePlaceholder}
            rows={1}
            disabled={disabled}
            maxLength={maxChars + 100}
            className={cn(
              'flex-1 resize-none bg-transparent py-3 text-[15px] leading-relaxed outline-none',
              'text-text-primary dark:text-text-dark-primary',
              'placeholder:text-text-tertiary dark:placeholder:text-text-dark-tertiary',
              'disabled:opacity-50 scrollbar-thin'
            )}
          />

          <div className="flex items-center gap-1 pr-2.5 pb-2">
            <button
              type="button"
              onClick={handleMicClick}
              disabled={isLoading || disabled || isTranscribing}
              title={isQuickRecording ? 'Stop and transcribe' : 'Voice input'}
              className={cn(
                'flex items-center justify-center p-2 rounded-lg transition-colors disabled:opacity-40',
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
              disabled={isLoading || disabled}
              title="Voice mode"
              className="flex items-center justify-center p-2 rounded-lg text-text-tertiary hover:text-text-primary dark:text-text-dark-tertiary dark:hover:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors disabled:opacity-40"
            >
              <AudioLines className="w-4 h-4" />
            </button>
            {isLoading ? (
              <button
                type="button"
                onClick={onStop}
                className="flex items-center gap-1.5 p-2 rounded-lg bg-red-500 hover:bg-red-600 text-white text-sm font-medium transition-colors"
                title="Stop generation"
              >
                <Square className="w-4 h-4 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSend}
                disabled={(!value.trim() && files.length === 0) || disabled}
                className={cn(
                  'flex items-center gap-1.5 p-2 rounded-lg transition-colors',
                  (value.trim() || files.length > 0)
                    ? 'bg-accent hover:bg-accent-hover text-white'
                    : 'bg-surface-tertiary dark:bg-surface-dark-tertiary text-text-tertiary dark:text-text-dark-tertiary cursor-not-allowed'
                )}
                title="Send message"
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between mt-1.5 px-1">
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-text-tertiary dark:text-text-dark-tertiary">
              Enter to send · Shift+Enter for new line
            </span>
          </div>
          {/* Only surface the counter once it's actually relevant — at a 50k
              cap, showing "23/50000" on every short message is just noise. */}
          {isNearLimit && (
            <span className={cn(
              'text-[11px] tabular-nums',
              isOverLimit ? 'text-red-500' : 'text-amber-500'
            )}>
              {charCount}/{maxChars}
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
