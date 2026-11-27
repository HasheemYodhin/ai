import type { ReactNode } from 'react'
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient, HttpResponseError, TerminalChatError } from '@/api/client'
import { FLUX_IMAGE_MODEL } from '@/lib/models'
import { SettingsProvider } from '@/hooks/useSettings'
import { useChat } from '@/hooks/useChat'
import type { Message } from '@/types'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

function wrapper({ children }: { children: ReactNode }) {
  return <SettingsProvider>{children}</SettingsProvider>
}

describe('useChat multi-conversation execution', () => {
  afterEach(() => vi.restoreAllMocks())

  it('keeps running replies attached to their original conversations', async () => {
    const first = deferred<string>()
    const second = deferred<string>()
    vi.spyOn(apiClient, 'chat')
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise)

    const updates = new Map<string, Message[]>()
    const onConversationUpdate = (id: string, messages: Message[]) => {
      updates.set(id, messages)
    }
    const { result, rerender } = renderHook(
      ({ activeConversationId }) => useChat({ activeConversationId, onConversationUpdate }),
      { initialProps: { activeConversationId: 'chat-a' }, wrapper },
    )

    act(() => result.current.setMessages([], 'chat-a'))
    let firstRun!: Promise<void>
    act(() => {
      firstRun = result.current.sendMessage('first question', undefined, { conversationId: 'chat-a' })
    })
    expect(result.current.isLoading).toBe(true)

    rerender({ activeConversationId: 'chat-b' })
    act(() => result.current.setMessages([], 'chat-b'))
    expect(result.current.isLoading).toBe(false)

    let secondRun!: Promise<void>
    act(() => {
      secondRun = result.current.sendMessage('second question', undefined, { conversationId: 'chat-b' })
    })

    await act(async () => {
      first.resolve('first answer')
      await firstRun
    })
    const chatA = updates.get('chat-a') ?? []
    expect(chatA[chatA.length - 1]?.content).toBe('first answer')
    expect(result.current.messages.some(message => message.content === 'first answer')).toBe(false)

    await act(async () => {
      second.resolve('second answer')
      await secondRun
    })
    expect(result.current.messages[result.current.messages.length - 1]?.content).toBe('second answer')
    const chatB = updates.get('chat-b') ?? []
    expect(chatB[chatB.length - 1]?.content).toBe('second answer')
  })
  it.each([
    { failure: new TerminalChatError('VyceAI rejected the request.'), recoverable: false },
    { failure: new HttpResponseError(400, 'Invalid request.'), recoverable: false },
    { failure: new HttpResponseError(409, 'Request already submitted.'), recoverable: true },
    { failure: new TypeError('Connection lost.'), recoverable: true },
  ])('keeps recovery only for uncertain failures ($failure.message)', async ({ failure, recoverable }) => {
    vi.spyOn(apiClient, 'chat').mockRejectedValue(failure)
    const { result } = renderHook(() => useChat({ activeConversationId: 'chat' }), { wrapper })
    await act(async () => { await result.current.sendMessage('Hello') })

    const reply = result.current.messages.slice(-1)[0]!
    expect(reply.content).toBe(failure.message)
    expect(Boolean(reply.recoveryRequestId)).toBe(recoverable)
    if (recoverable) {
      vi.spyOn(apiClient, 'recoverChatReply').mockRejectedValue(new HttpResponseError(404, 'No recoverable reply was found.'))
      await act(async () => { await result.current.recoverReply(reply.id) })
      expect(result.current.messages.slice(-1)[0]?.recoveryRequestId).toBeUndefined()
      expect(result.current.messages.slice(-1)[0]?.content).toBe(failure.message)
    }
  })

  it('retries an old FLUX error on the image endpoint using the original prompt', async () => {
    const chat = vi.spyOn(apiClient, 'chat')
    const image = vi.spyOn(apiClient, 'generateImages').mockResolvedValue(['data:image/png;base64,example'])
    const { result } = renderHook(() => useChat({ activeConversationId: 'chat' }), { wrapper })
    act(() => result.current.setMessages([
      { id: 'prompt', role: 'user', content: 'Draw a mountain', timestamp: 1 },
      { id: 'reply', role: 'assistant', content: 'Previous routing error', model: FLUX_IMAGE_MODEL, error: true, timestamp: 2 },
    ]))
    await act(async () => { await result.current.regenerate('reply') })

    expect(chat).not.toHaveBeenCalled()
    expect(image).toHaveBeenCalledWith('Draw a mountain', expect.objectContaining({ model: FLUX_IMAGE_MODEL }))
    expect(result.current.messages.slice(-1)[0]?.generatedImages).toEqual(['data:image/png;base64,example'])
  })

})
