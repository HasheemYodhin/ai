import { useEffect, useRef, useState } from 'react'
import { Square, X, Loader2, Mic } from 'lucide-react'
import { startRecording, watchAudioLevel, type VoiceRecorder } from '@/lib/voice'
import { apiClient } from '@/api/client'
import { useTheme } from '@/hooks/useTheme'

interface VoiceRecordingModalProps {
  onClose: () => void
  onTranscribed: (text: string) => void
}

/** Full "voice mode" overlay — live waveform while recording, then transcribes on stop. */
export function VoiceRecordingModal({ onClose, onTranscribed }: VoiceRecordingModalProps) {
  const [error, setError] = useState<string | null>(null)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const recorderRef = useRef<VoiceRecorder | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const levelsRef = useRef<number[]>(new Array(48).fill(0))
  const { theme } = useTheme()

  useEffect(() => {
    let stopWatching: (() => void) | null = null
    let cancelled = false

    startRecording()
      .then(async (recorder) => {
        if (cancelled) { recorder.cancel(); return }
        recorderRef.current = recorder
        stopWatching = watchAudioLevel(recorder.stream, (level) => {
          levelsRef.current = [...levelsRef.current.slice(1), level]
        })
      })
      .catch(err => setError((err as Error).message || 'Could not access the microphone'))

    const timer = setInterval(() => setElapsed(e => e + 1), 1000)

    let rafId: number
    const draw = () => {
      const canvas = canvasRef.current
      const ctx = canvas?.getContext('2d')
      if (canvas && ctx) {
        const dpr = window.devicePixelRatio || 1
        const w = canvas.clientWidth, h = canvas.clientHeight
        if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
          canvas.width = w * dpr
          canvas.height = h * dpr
        }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        ctx.clearRect(0, 0, w, h)
        const barWidth = w / levelsRef.current.length
        const accent = theme === 'dark' ? '#e08a6a' : '#c96442'
        levelsRef.current.forEach((level, i) => {
          const barHeight = Math.max(3, level * h * 0.9)
          ctx.fillStyle = accent
          ctx.globalAlpha = 0.35 + level * 0.65
          ctx.fillRect(i * barWidth + barWidth * 0.25, (h - barHeight) / 2, barWidth * 0.5, barHeight)
        })
      }
      rafId = requestAnimationFrame(draw)
    }
    draw()

    return () => {
      cancelled = true
      clearInterval(timer)
      cancelAnimationFrame(rafId)
      stopWatching?.()
      recorderRef.current?.cancel()
    }
  }, [theme])

  const handleStop = async () => {
    const recorder = recorderRef.current
    if (!recorder) { onClose(); return }
    setIsTranscribing(true)
    try {
      const blob = await recorder.stop()
      const text = await apiClient.transcribeAudio(blob)
      if (text) onTranscribed(text)
      onClose()
    } catch (err) {
      setError((err as Error).message || 'Transcription failed')
      setIsTranscribing(false)
    }
  }

  const handleCancel = () => {
    recorderRef.current?.cancel()
    onClose()
  }

  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0')
  const ss = String(elapsed % 60).padStart(2, '0')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 animate-fade-in">
      <div className="bg-surface dark:bg-surface-dark-secondary rounded-2xl border border-border dark:border-border-dark shadow-xl w-full max-w-sm m-4 p-6 flex flex-col items-center">
        <button onClick={handleCancel} className="absolute top-4 right-4 p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary transition-colors">
          <X className="w-4 h-4" />
        </button>

        <div className="w-14 h-14 rounded-full bg-accent/10 flex items-center justify-center mb-4">
          {isTranscribing ? (
            <Loader2 className="w-6 h-6 text-accent animate-spin" />
          ) : (
            <Mic className="w-6 h-6 text-accent" />
          )}
        </div>

        <p className="text-sm font-medium text-text-primary dark:text-text-dark-primary mb-1">
          {isTranscribing ? 'Transcribing…' : error ? 'Microphone error' : 'Listening…'}
        </p>

        {error ? (
          <p className="text-xs text-red-500 text-center mt-1 mb-4">{error}</p>
        ) : (
          <p className="text-xs text-text-tertiary dark:text-text-dark-tertiary mb-4 tabular-nums">{mm}:{ss}</p>
        )}

        <canvas ref={canvasRef} className="w-full h-16 mb-5" />

        <div className="flex items-center gap-2 w-full">
          <button
            onClick={handleCancel}
            className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleStop}
            disabled={isTranscribing || !!error}
            className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-semibold bg-accent hover:bg-accent-hover disabled:opacity-50 text-white transition-colors"
          >
            <Square className="w-3.5 h-3.5 fill-current" /> Stop
          </button>
        </div>
      </div>
    </div>
  )
}
