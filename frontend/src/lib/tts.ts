import { apiClient } from '@/api/client'

let stopCurrent: (() => void) | undefined

export function speak(text: string, onDone?: () => void, onError?: (message: string) => void): { stop: () => void } {
  stopSpeaking()
  const abort = new AbortController()
  let cleanup = () => {}
  const stop = () => {
    if (abort.signal.aborted) return
    abort.abort()
    cleanup()
    if (stopCurrent === stop) stopCurrent = undefined
    onDone?.()
  }
  stopCurrent = stop

  const play = async () => {
    const status = await apiClient.audioStatus(abort.signal).catch(() => null)
    if (abort.signal.aborted) return
    if (status?.speech?.available !== false) {
      try {
        const blob = await apiClient.synthesizeSpeech(text, { signal: abort.signal })
        if (abort.signal.aborted) return
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        cleanup = () => {
          audio.onended = audio.onerror = null
          audio.pause()
          URL.revokeObjectURL(url)
        }
        audio.onended = stop
        audio.onerror = () => { stop(); onError?.('Could not play the generated audio.') }
        await audio.play()
        return
      } catch (error) {
        if (abort.signal.aborted) return
        cleanup()
        if (!window.speechSynthesis) throw error
      }
    }

    if (!window.speechSynthesis || typeof SpeechSynthesisUtterance === 'undefined') {
      throw new Error('Read aloud needs browser speech synthesis or a Dabba server with speech enabled.')
    }
    const utterance = new SpeechSynthesisUtterance(text.slice(0, 4000))
    utterance.lang = navigator.language
    const voice = window.speechSynthesis.getVoices().find(item => item.localService && item.lang === utterance.lang)
    if (voice) utterance.voice = voice
    cleanup = () => {
      utterance.onend = utterance.onerror = null
      window.speechSynthesis.cancel()
    }
    utterance.onend = stop
    utterance.onerror = event => {
      stop()
      onError?.(`Browser read aloud failed (${event.error}).`)
    }
    window.speechSynthesis.speak(utterance)
    return
  }
  void play().catch(error => {
    if (abort.signal.aborted) return
    stop()
    onError?.(error instanceof Error ? error.message : 'Speech failed')
  })
  return { stop }
}

export function stopSpeaking(): void {
  stopCurrent?.()
}
