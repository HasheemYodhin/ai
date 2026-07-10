import { apiClient } from '@/api/client'

let currentAudio: HTMLAudioElement | null = null

/**
 * Speaks text aloud via the backend's offline Piper TTS. Stops any
 * currently-playing speech first — only one reply should be talking at once.
 * Returns a controller so callers can track state (e.g. a play/stop button).
 */
export async function speak(text: string, onDone?: () => void): Promise<{ stop: () => void }> {
  stopSpeaking()

  const blob = await apiClient.synthesizeSpeech(text)
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  currentAudio = audio

  const cleanup = () => {
    URL.revokeObjectURL(url)
    if (currentAudio === audio) currentAudio = null
    onDone?.()
  }
  audio.onended = cleanup
  audio.onerror = cleanup

  await audio.play()
  return { stop: () => { audio.pause(); cleanup() } }
}

export function stopSpeaking(): void {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio = null
  }
}
