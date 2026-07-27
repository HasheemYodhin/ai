import type { ReactNode } from 'react'
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/client'
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
})
