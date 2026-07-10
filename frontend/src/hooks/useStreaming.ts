import { useState, useRef, useEffect, useCallback } from 'react'
import { apiClient } from '@/api/client'
import type { Message, StreamChunk } from '@/types'

interface UseStreamingOptions {
  onChunk?: (chunk: StreamChunk) => void
  onError?: (error: Error) => void
  onDone?: (fullContent: string) => void
}

interface UseStreamingReturn {
  isStreaming: boolean
  startStream: (messages: Message[], signal?: AbortSignal) => Promise<string>
  abortStream: () => void
  error: Error | null
}

export function useStreaming(options: UseStreamingOptions = {}): UseStreamingReturn {
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => {
      mountedRef.current = false
      abortRef.current?.abort()
    }
  }, [])

  const abortStream = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    setIsStreaming(false)
  }, [])

  const startStream = useCallback(async (
    messages: Message[],
    signal?: AbortSignal
  ): Promise<string> => {
    setIsStreaming(true)
    setError(null)

    const controller = new AbortController()
    abortRef.current = controller

    const combinedSignal = signal
      ? combineAbortSignals(controller.signal, signal)
      : controller.signal

    try {
      const content = await apiClient.chat(messages, {
        signal: combinedSignal,
        onChunk: (chunk) => {
          if (mountedRef.current) {
            options.onChunk?.(chunk)
            if (chunk.finishReason) {
              options.onDone?.(chunk.content)
            }
          }
        },
      })

      if (mountedRef.current) {
        options.onDone?.(content)
      }

      return content
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        if (mountedRef.current) setIsStreaming(false)
        return ''
      }
      const error = err as Error
      if (mountedRef.current) {
        setError(error)
        options.onError?.(error)
      }
      throw error
    } finally {
      if (mountedRef.current) setIsStreaming(false)
      abortRef.current = null
    }
  }, [options])

  return {
    isStreaming,
    startStream,
    abortStream,
    error,
  }
}

function combineAbortSignals(...signals: AbortSignal[]): AbortSignal {
  const controller = new AbortController()

  for (const signal of signals) {
    if (signal.aborted) {
      controller.abort(signal.reason)
      return controller.signal
    }
    signal.addEventListener('abort', () => controller.abort(signal.reason), { once: true })
  }

  return controller.signal
}
