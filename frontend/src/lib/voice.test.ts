import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/client'
import { startVoiceInput } from './voice'
import { speak, stopSpeaking } from './tts'

const unavailable = {
  transcription: { available: false, whisperInstalled: false, ffmpegInstalled: false },
  speech: { available: false },
}

afterEach(() => {
  stopSpeaking()
  vi.unstubAllGlobals()
})

describe('browser speech fallbacks', () => {
  it('returns a browser transcript when the server cannot transcribe', async () => {
    vi.spyOn(apiClient, 'audioStatus').mockResolvedValue(unavailable)
    const transcribe = vi.spyOn(apiClient, 'transcribeAudio')
    class Recognition extends EventTarget {
      start() {}
      stop() {
        this.dispatchEvent(Object.assign(new Event('result'), {
          resultIndex: 0,
          results: [{ isFinal: true, 0: { transcript: 'hello from the microphone' } }],
        }))
        this.dispatchEvent(new Event('end'))
      }
    }
    vi.stubGlobal('webkitSpeechRecognition', Recognition)

    const recording = await startVoiceInput()
    await expect(recording.stop()).resolves.toBe('hello from the microphone')
    expect(transcribe).not.toHaveBeenCalled()
  })

  it('reads aloud through the browser when Piper is unavailable', async () => {
    vi.spyOn(apiClient, 'audioStatus').mockResolvedValue(unavailable)
    const synthesize = vi.spyOn(apiClient, 'synthesizeSpeech')
    const browserSpeak = vi.fn()
    const cancel = vi.fn()
    vi.stubGlobal('speechSynthesis', { speak: browserSpeak, cancel, getVoices: () => [] })
    vi.stubGlobal('SpeechSynthesisUtterance', class {
      constructor(readonly text: string) {}
    })

    const onDone = vi.fn()
    const playback = speak('hello from Dabba', onDone)
    await vi.waitFor(() => expect(browserSpeak).toHaveBeenCalledWith(expect.objectContaining({ text: 'hello from Dabba' })))
    playback.stop()
    expect(cancel).toHaveBeenCalledOnce()
    expect(onDone).toHaveBeenCalledOnce()
    expect(synthesize).not.toHaveBeenCalled()
  })
})
