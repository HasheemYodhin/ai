import { useState, useCallback, useRef } from 'react'
import { v4 as uuidv4 } from 'uuid'
import { apiClient } from '@/api/client'
import type { Message, AgentStep } from '@/types'
import { useSettings } from '@/hooks/useSettings'
import { isVisionModel } from '@/lib/models'
import { ocrImages } from '@/lib/ocr'

interface UseChatReturn {
  messages: Message[]
  isLoading: boolean
  error: string | null
  addMessage: (content: string, role?: Message['role'], extra?: Partial<Message>) => Message
  updateMessage: (id: string, updates: Partial<Message>) => void
  clearMessages: () => void
  sendMessage: (content: string, images?: string[], opts?: { systemPromptOverride?: string; viaVoice?: boolean }) => Promise<void>
  runAgentMode: (content: string, opts: { label: string; effort?: string; hint?: string; viaVoice?: boolean }) => Promise<void>
  generateImage: (prompt: string) => Promise<void>
  editMessage: (id: string, content: string) => Promise<void>
  regenerate: (id: string, overrides?: { model?: string; effort?: string }) => Promise<void>
  stopGeneration: () => void
  setMessages: (messages: Message[]) => void
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const { settings } = useSettings()

  const addMessage = useCallback((content: string, role: Message['role'] = 'user', extra?: Partial<Message>): Message => {
    const message: Message = {
      id: uuidv4(),
      role,
      content,
      timestamp: Date.now(),
      ...extra,
    }
    setMessages(prev => [...prev, message])
    return message
  }, [])

  const updateMessage = useCallback((id: string, updates: Partial<Message>) => {
    setMessages(prev =>
      prev.map(m => (m.id === id ? { ...m, ...updates } : m))
    )
  }, [])

  const clearMessages = useCallback(() => {
    setMessages([])
    setError(null)
  }, [])

  const stopGeneration = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    setIsLoading(false)
  }, [])

  const runCompletion = useCallback(async (
    historyMessages: Message[],
    assistantId: string,
    overrides?: { model?: string; effort?: string; systemPromptOverride?: string },
  ) => {
    setError(null)
    setIsLoading(true)

    const abortController = new AbortController()
    abortRef.current = abortController

    const model = overrides?.model ?? settings.model
    const effort = overrides?.effort ?? settings.effort
    const systemPrompt = overrides?.systemPromptOverride ?? settings.systemPrompt

    const apiMessages = [...historyMessages]
    if (systemPrompt) {
      apiMessages.unshift({
        id: 'system-prompt',
        role: 'system',
        content: systemPrompt,
        timestamp: Date.now()
      })
    }

    let lastUsage: Message['usage']

    const chatParams = {
      model,
      effort,
      temperature: settings.temperature,
      max_tokens: settings.maxTokens,
      top_p: settings.topP,
      presence_penalty: settings.presencePenalty,
      frequency_penalty: settings.frequencyPenalty,
      stop: settings.stop,
    }

    try {
      if (!settings.streaming) {
        // Non-streaming: one blocking call, then drop the whole reply in at once.
        const full = await apiClient.chat(apiMessages, { signal: abortController.signal, ...chatParams })
        updateMessage(assistantId, { content: full, model, timestamp: Date.now() })
      } else
      await apiClient.chat(
        apiMessages,
        {
          signal: abortController.signal,
          ...chatParams,
          onChunk: (chunk) => {
            if (chunk.usage) lastUsage = chunk.usage
            updateMessage(assistantId, {
              content: chunk.content,
              model,
              ...(chunk.finishReason ? { timestamp: Date.now() } : {}),
            })
          },
        }
      )
      // Fall back to a rough token estimate when the server doesn't report usage.
      updateMessage(assistantId, {
        error: false,
        model,
        usage: lastUsage,
      })
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        updateMessage(assistantId, { timestamp: Date.now() })
      } else {
        const errorMessage = (err as Error).message || 'An unexpected error occurred'
        updateMessage(assistantId, {
          content: errorMessage,
          error: true,
          model,
          timestamp: Date.now(),
        })
        setError(errorMessage)
      }
    } finally {
      setIsLoading(false)
      abortRef.current = null
    }
  }, [settings, updateMessage])

  const sendMessage = useCallback(async (content: string, images?: string[], opts?: { systemPromptOverride?: string; viaVoice?: boolean }) => {
    if ((!content.trim() && !images?.length) || isLoading) return

    let userMessage: Message
    if (images?.length) {
      if (isVisionModel(settings.model)) {
        // Vision model: attach images as multimodal parts (sent by the client).
        userMessage = addMessage(content, 'user', { images, imageMode: 'vision', viaVoice: opts?.viaVoice })
      } else {
        // Non-vision model: OCR the images to text and bake it into the prompt,
        // but keep the thumbnails for display.
        setIsLoading(true)
        let ocrText = ''
        try {
          ocrText = await ocrImages(images)
        } catch (err) {
          ocrText = `[OCR failed: ${(err as Error).message}]`
        }
        setIsLoading(false)
        const augmented = ocrText
          ? `${content}\n\n[Text extracted from image(s)]:\n${ocrText}`.trim()
          : content
        userMessage = addMessage(augmented, 'user', { images, imageMode: 'ocr', viaVoice: opts?.viaVoice })
      }
    } else {
      userMessage = addMessage(content, 'user', { viaVoice: opts?.viaVoice })
    }

    const assistantMessage = addMessage('', 'assistant', { viaVoice: opts?.viaVoice })
    await runCompletion([...messages, userMessage], assistantMessage.id, opts)
  }, [messages, isLoading, addMessage, runCompletion, settings.model])

  /** Best-effort human summary of a tool call's arguments for the activity trace. */
  function summarizeToolArgs(args: unknown): string {
    if (!args || typeof args !== 'object') return ''
    const a = args as Record<string, unknown>
    const preferred = a.query ?? a.url ?? a.command ?? a.path ?? a.title
    if (typeof preferred === 'string') return preferred
    try { return JSON.stringify(a).slice(0, 100) } catch { return '' }
  }

  // Drives one turn of the real Dabba agent loop — the same tool-using loop
  // (web search, MCP connectors/plugins, shell/file tools) the VS Code
  // extension's chat panel drives. Powers Web Search, Connectors, Plugins,
  // and Research from the "+" menu; only the label/effort/hint differ.
  //
  // Note: the agent endpoint keeps its own conversation memory server-side
  // (see client.streamAgent's docstring) — it only sees the latest message,
  // not this hook's full `messages` history, so it's best used for one-off
  // lookups rather than as a drop-in replacement for the normal chat turn.
  const runAgentMode = useCallback(async (content: string, opts: { label: string; effort?: string; hint?: string; viaVoice?: boolean }) => {
    if (!content.trim() || isLoading) return

    addMessage(content, 'user', { viaVoice: opts.viaVoice })
    const assistantMessage = addMessage('', 'assistant', { agentActivity: { label: opts.label, steps: [], done: false }, viaVoice: opts.viaVoice })

    setError(null)
    setIsLoading(true)
    const abortController = new AbortController()
    abortRef.current = abortController

    let textParts: string[] = []
    const steps: AgentStep[] = []

    const sendText = opts.hint ? `${opts.hint}\n\n${content}` : content

    try {
      await apiClient.streamAgent(sendText, {
        signal: abortController.signal,
        model: settings.model,
        effort: opts.effort ?? settings.effort,
        onEvent: (event) => {
          if (event.type === 'tool_call') {
            const c = event.content as { name?: string; arguments?: unknown }
            steps.push({ tool: c?.name ?? 'tool', detail: summarizeToolArgs(c?.arguments) })
            updateMessage(assistantMessage.id, { agentActivity: { label: opts.label, steps: [...steps], done: false } })
          } else if (event.type === 'tool_result') {
            const c = event.content as { tool?: string; success?: boolean; output?: unknown }
            // Best-effort match to the most recent step for this tool name.
            const idx = steps.map((s, i) => ({ s, i })).reverse().find(({ s }) => s.tool === c?.tool)?.i
            if (idx != null) steps[idx] = { ...steps[idx], success: c?.success }
            updateMessage(assistantMessage.id, { agentActivity: { label: opts.label, steps: [...steps], done: false } })
          } else if (event.type === 'text') {
            textParts = [...textParts, String(event.content ?? '')]
            updateMessage(assistantMessage.id, { content: textParts.join('\n\n') })
          } else if (event.type === 'error') {
            throw new Error(String(event.content ?? 'Agent error'))
          }
        },
      })
      updateMessage(assistantMessage.id, {
        model: settings.model,
        timestamp: Date.now(),
        agentActivity: { label: opts.label, steps, done: true },
      })
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        updateMessage(assistantMessage.id, { timestamp: Date.now(), agentActivity: { label: opts.label, steps, done: true } })
      } else {
        const errorMessage = (err as Error).message || `${opts.label} failed`
        updateMessage(assistantMessage.id, {
          content: errorMessage,
          error: true,
          timestamp: Date.now(),
          agentActivity: { label: opts.label, steps, done: true },
        })
        setError(errorMessage)
      }
    } finally {
      setIsLoading(false)
      abortRef.current = null
    }
  }, [isLoading, addMessage, updateMessage, settings.model, settings.effort])

  // Generates images from a prompt via /v1/images/generations (proxies to
  // whichever image-capable provider has a key configured — currently OpenAI).
  const generateImage = useCallback(async (prompt: string) => {
    if (!prompt.trim() || isLoading) return

    addMessage(prompt, 'user')
    const assistantMessage = addMessage('', 'assistant', { isGeneratingImage: true })

    setError(null)
    setIsLoading(true)
    const abortController = new AbortController()
    abortRef.current = abortController

    try {
      const images = await apiClient.generateImages(prompt, { signal: abortController.signal })
      updateMessage(assistantMessage.id, {
        generatedImages: images,
        isGeneratingImage: false,
        timestamp: Date.now(),
      })
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        updateMessage(assistantMessage.id, { isGeneratingImage: false, timestamp: Date.now() })
      } else {
        const errorMessage = (err as Error).message || 'Image generation failed'
        updateMessage(assistantMessage.id, {
          content: errorMessage,
          error: true,
          isGeneratingImage: false,
          timestamp: Date.now(),
        })
        setError(errorMessage)
      }
    } finally {
      setIsLoading(false)
      abortRef.current = null
    }
  }, [isLoading, addMessage, updateMessage])

  // Edits a user message in place, drops everything after it, and re-runs the assistant turn.
  const editMessage = useCallback(async (id: string, content: string) => {
    if (!content.trim() || isLoading) return

    const index = messages.findIndex(m => m.id === id)
    if (index === -1) return

    const editedMessage: Message = { ...messages[index], content, timestamp: Date.now() }
    const truncated = messages.slice(0, index)
    const assistantMessage: Message = { id: uuidv4(), role: 'assistant', content: '', timestamp: Date.now() }

    setMessages([...truncated, editedMessage, assistantMessage])
    await runCompletion([...truncated, editedMessage], assistantMessage.id)
  }, [messages, isLoading, runCompletion])

  // Regenerates an assistant reply (also serves as retry-on-error), optionally
  // with a different model/effort than the current settings.
  const regenerate = useCallback(async (id: string, overrides?: { model?: string; effort?: string }) => {
    if (isLoading) return

    const index = messages.findIndex(m => m.id === id)
    if (index === -1) return

    const history = messages.slice(0, index)
    const assistantMessage: Message = { id: uuidv4(), role: 'assistant', content: '', timestamp: Date.now() }

    setMessages([...history, assistantMessage])
    await runCompletion(history, assistantMessage.id, overrides)
  }, [messages, isLoading, runCompletion])

  return {
    messages,
    isLoading,
    error,
    addMessage,
    updateMessage,
    clearMessages,
    sendMessage,
    runAgentMode,
    generateImage,
    editMessage,
    regenerate,
    stopGeneration,
    setMessages,
  }
}
