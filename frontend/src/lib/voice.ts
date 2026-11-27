import { apiClient } from '@/api/client'

const MAX_RECORDING_MS = 2 * 60 * 1000
/**
 * Browser-side microphone capture. Records via MediaRecorder in whatever
 * format the browser natively produces (WebM/Opus in Chrome/Firefox) — the
 * backend's /v1/transcribe decodes it with ffmpeg regardless of container,
 * so no client-side transcoding is needed (verified against the real
 * endpoint: a genuine WebM/Opus file round-trips cleanly).
 */
export interface VoiceRecorder {
  stop: () => Promise<Blob>
  cancel: () => void
  stream: MediaStream
}

export async function startRecording(): Promise<VoiceRecorder> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('Microphone access is not supported in this browser')
  }

  if (typeof MediaRecorder === 'undefined') throw new Error('Audio recording is not supported in this browser')

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true }).catch(error => {
    if (error instanceof DOMException && error.name === 'NotAllowedError') {
      throw new Error('Allow microphone access in your browser, then try again.')
    }
    if (error instanceof DOMException && error.name === 'NotFoundError') {
      throw new Error('Connect or enable a microphone, then try again.')
    }
    throw error
  })
  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : MediaRecorder.isTypeSupported('audio/webm')
      ? 'audio/webm'
      : '' // let the browser pick a default if neither is supported

  const stopTracks = () => stream.getTracks().forEach(track => track.stop())
  const chunks: Blob[] = []
  let recorder: MediaRecorder
  try {
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    recorder.ondataavailable = event => { if (event.data.size > 0) chunks.push(event.data) }
    recorder.start()
  } catch (error) {
    stopTracks()
    throw error
  }

  const stopRecorder = () => {
    if (recorder.state !== 'inactive') recorder.stop()
    stopTracks()
  }
  const timer = window.setTimeout(stopRecorder, MAX_RECORDING_MS)
  const recording = new Promise<Blob>(resolve => {
    recorder.onstop = () => {
      window.clearTimeout(timer)
      stopTracks()
      resolve(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }))
    }
  })

  return {
    stream,
    stop: () => { stopRecorder(); return recording },
    cancel: stopRecorder,
  }
}

/** Live input-level samples (0..1) for a waveform visualizer, driven by requestAnimationFrame. */
export function watchAudioLevel(stream: MediaStream, onLevel: (level: number) => void): () => void {
  const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
  const ctx = new AudioCtx()
  const source = ctx.createMediaStreamSource(stream)
  const analyser = ctx.createAnalyser()
  analyser.fftSize = 256
  source.connect(analyser)

  const data = new Uint8Array(analyser.frequencyBinCount)
  let rafId: number
  let stopped = false

  const tick = () => {
    if (stopped) return
    analyser.getByteTimeDomainData(data)
    let sumSquares = 0
    for (let i = 0; i < data.length; i++) {
      const normalized = (data[i] - 128) / 128
      sumSquares += normalized * normalized
    }
    onLevel(Math.min(1, Math.sqrt(sumSquares / data.length) * 4))
    rafId = requestAnimationFrame(tick)
  }
  tick()

  return () => {
    stopped = true
    cancelAnimationFrame(rafId)
    source.disconnect()
    ctx.close()
  }
}

export const VOICE_UNAVAILABLE = "Voice input needs a browser with speech recognition or a Dabba server with transcription enabled."

export interface VoiceInput {
  stream?: MediaStream
  stop: () => Promise<string>
  cancel: () => void
}

interface BrowserRecognition extends EventTarget {
  continuous: boolean
  lang: string
  start(): void
  stop(): void
  abort(): void
}

type RecognitionWindow = Window & {
  SpeechRecognition?: new () => BrowserRecognition
  webkitSpeechRecognition?: new () => BrowserRecognition
}

function startBrowserVoiceInput(): VoiceInput {
  const browser = window as RecognitionWindow
  const Recognition = browser.SpeechRecognition ?? browser.webkitSpeechRecognition
  if (!Recognition) throw new Error(VOICE_UNAVAILABLE)

  const recognition = new Recognition()
  recognition.continuous = true
  recognition.lang = navigator.language
  let transcript = ''
  let failure = ''
  let ended = false
  let finish: () => void = () => {}
  recognition.addEventListener('result', event => {
    const { results, resultIndex } = event as Event & {
      results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>
      resultIndex: number
    }
    for (let index = resultIndex; index < results.length; index++) {
      if (results[index].isFinal) transcript += ` ${results[index][0].transcript}`
    }
  })
  recognition.addEventListener('error', event => {
    const error = (event as Event & { error: string }).error
    if (error === 'no-speech' || error === 'aborted') return
    failure = error === 'not-allowed' || error === 'service-not-allowed'
      ? 'Allow microphone access in your browser to use voice input.'
      : `Browser speech recognition failed (${error}). Check your microphone and connection.`
  })
  const limit = window.setTimeout(() => { if (!ended) recognition.stop() }, MAX_RECORDING_MS)
  recognition.addEventListener('end', () => {
    window.clearTimeout(limit)
    ended = true
    finish()
  })
  try { recognition.start() } catch (error) { window.clearTimeout(limit); throw error }

  return {
    stop: async () => {
      if (!ended) {
        await new Promise<void>(resolve => {
          const timer = window.setTimeout(() => {
            recognition.abort()
            resolve()
          }, 5000)
          finish = () => { window.clearTimeout(timer); resolve() }
          recognition.stop()
        })
      }
      if (failure) throw new Error(failure)
      return transcript.trim()
    },
    cancel: () => { if (!ended) recognition.abort() },
  }
}

export async function startVoiceInput(signal?: AbortSignal): Promise<VoiceInput> {
  const status = await apiClient.audioStatus(signal).catch(() => null)
  signal?.throwIfAborted()
  if (status && !status.transcription.available) return startBrowserVoiceInput()
  const recorder = await startRecording()
  return {
    stream: recorder.stream,
    cancel: recorder.cancel,
    stop: async () => {
      const blob = await recorder.stop()
      signal?.throwIfAborted()
      return apiClient.transcribeAudio(blob, { signal })
    },
  }
}

/** The server's setup instructions are for administrators; show visitors something they can act on. */
export function friendlyVoiceError(message: string): { text: string; unavailable: boolean } {
  if (message === VOICE_UNAVAILABLE || /ffmpeg is required|whisper is not installed/i.test(message)) return { text: VOICE_UNAVAILABLE, unavailable: true }
  return { text: message, unavailable: false }
}
