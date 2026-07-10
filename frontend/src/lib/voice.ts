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

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : MediaRecorder.isTypeSupported('audio/webm')
      ? 'audio/webm'
      : '' // let the browser pick a default if neither is supported

  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
  const chunks: Blob[] = []
  recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data) }
  recorder.start()

  const stopTracks = () => stream.getTracks().forEach(t => t.stop())

  return {
    stream,
    stop: () => new Promise<Blob>((resolve) => {
      recorder.onstop = () => {
        stopTracks()
        resolve(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }))
      }
      recorder.stop()
    }),
    cancel: () => {
      recorder.onstop = null
      if (recorder.state !== 'inactive') recorder.stop()
      stopTracks()
    },
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
