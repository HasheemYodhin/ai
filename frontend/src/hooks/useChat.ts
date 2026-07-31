import { useState, useCallback, useRef } from 'react'
import { v4 as uuidv4 } from 'uuid'
import { apiClient } from '@/api/client'
import type { Message, AgentStep, ExtractedDocument, DocumentAttachment } from '@/types'
import { useSettings } from '@/hooks/useSettings'
import { isVisionModel } from '@/lib/models'
import { ocrImages } from '@/lib/ocr'
import { createGeneratedDocument, type DocumentFormat } from '@/lib/download'

const FILE_EXPORT_CAPABILITY = [
  'This chat client can create and attach real PDF, Word (.docx), Excel (.xlsx),',
  'and PowerPoint (.pptx) files from your response. When the user asks for one',
  'of these formats, or asks to edit an attached document, provide the complete',
  'revised content for the whole file, not only a description of the changes.',
  'For Excel, use markdown tables that preserve all rows and columns. For',
  'PowerPoint, use markdown headings for slide titles and bullets for slide content.',
  'Return only the final revised document content. Do not narrate your plan,',
  'repeat the request, expose internal reasoning, or say what you are about to do.',
  'Never claim that you cannot create binary files, never ask the user to copy',
  'and paste the response, and do not substitute extracted text for the requested file.',
].join(' ')

const EDIT_DOCUMENT_RE = /\b(edit|update|change|modify|improve|replace|remove|delete|add|append|insert|fix|correct|rewrite|revise|translate|reformat|rename)\b/i
const NVIDIA_CAPACITY_RE = /(?:resourceexhausted|worker\s+local\s+total\s+request\s+limit\s+reached)/i
const DOCUMENT_FALLBACK_MODEL = 'meta/llama-3.1-8b-instruct'
const GENERAL_FALLBACK_MODEL = 'qwen/qwen2.5-coder-32b-instruct'

function withoutCapacityError(content: string): string {
  const marker = content.search(/I encountered an error calling|ResourceExhausted|Worker local total request limit reached/i)
  return marker >= 0 ? content.slice(0, marker).trimEnd() : content
}

function attachmentDocumentFormat(attachment: DocumentAttachment): DocumentFormat | null {
  const name = attachment.name.toLowerCase()
  if (attachment.type === 'application/pdf' || name.endsWith('.pdf')) return 'pdf'
  if (attachment.type.includes('wordprocessingml') || name.endsWith('.docx')) return 'docx'
  if (attachment.type.includes('spreadsheetml') || name.endsWith('.xlsx')) return 'xlsx'
  if (attachment.type.includes('presentationml') || name.endsWith('.pptx')) return 'pptx'
  return null
}

function requestedDocumentFormats(
  prompt: string,
  attachments?: DocumentAttachment[],
): DocumentFormat[] {
  const asksForFile = /\b(create|generate|make|export|convert|save|give|provide|prepare|build|produce|download|need|want|write)\b/i.test(prompt)

  const formats: DocumentFormat[] = []
  if (asksForFile) {
    if (/\b(pdf|portable document)\b/i.test(prompt)) formats.push('pdf')
    if (/\b(docx|word(?:\s+(?:file|document))?|microsoft word)\b/i.test(prompt)) formats.push('docx')
    if (/\b(xlsx|excel|spreadsheet|workbook)\b/i.test(prompt)) formats.push('xlsx')
    if (/\b(pptx|powerpoint|presentation|slide deck|slides)\b/i.test(prompt)) formats.push('pptx')
  }

  if (formats.length === 0 && EDIT_DOCUMENT_RE.test(prompt)) {
    for (const attachment of attachments ?? []) {
      const format = attachmentDocumentFormat(attachment)
      if (format && !formats.includes(format)) formats.push(format)
    }
  }
  return formats
}

function generatedDocumentBaseName(message: Message, prompt = message.content): string {
  const attachmentName = message.documentAttachments?.[0]?.name
  if (attachmentName) {
    const stem = attachmentName.replace(/\.(pdf|docx|xlsx|pptx|txt|md|csv)$/i, '') || 'dabba-document'
    return EDIT_DOCUMENT_RE.test(prompt) ? `${stem}-edited` : stem
  }
  const usefulLine = message.content
    .split('\n')
    .map(line => line.trim())
    .find(Boolean)
  return usefulLine?.slice(0, 60) || 'dabba-document'
}

interface UseChatReturn {
  messages: Message[]
  isLoading: boolean
  runningConversationIds: string[]
  error: string | null
  addMessage: (content: string, role?: Message['role'], extra?: Partial<Message>) => Message
  updateMessage: (id: string, updates: Partial<Message>) => void
  clearMessages: () => void
  sendMessage: (content: string, images?: string[], opts?: { conversationId?: string; systemPromptOverride?: string; viaVoice?: boolean; documents?: ExtractedDocument[]; attachments?: DocumentAttachment[] }) => Promise<void>
  runAgentMode: (content: string, opts: { conversationId?: string; label: string; effort?: string; hint?: string; allowedTools?: string[]; viaVoice?: boolean }) => Promise<void>
  generateImage: (prompt: string, conversationId?: string) => Promise<void>
  editMessage: (id: string, content: string) => Promise<void>
  regenerate: (id: string, overrides?: { model?: string; effort?: string }) => Promise<void>
  stopGeneration: () => void
  setMessages: (messages: Message[], conversationId?: string) => void
  pendingApproval: PendingApproval | null
  respondToApproval: (approved: boolean) => void
  pendingPlanApproval: PendingPlanApproval | null
  respondToPlanApproval: (approved: boolean) => void
}

interface UseChatOptions {
  activeConversationId?: string | null
  onConversationUpdate?: (conversationId: string, messages: Message[]) => void
}

export interface PendingApproval {
  callId: string
  name: string
  arguments: unknown
}

export interface PendingPlanApproval {
  planId: string
  objective: string
  steps: Array<{ step_id: string; tool: string; description: string }>
}

export function useChat({ activeConversationId = null, onConversationUpdate }: UseChatOptions = {}): UseChatReturn {
  const [messages, setVisibleMessages] = useState<Message[]>([])
  const [runningConversations, setRunningConversations] = useState<Set<string>>(() => new Set())
  const [error, setError] = useState<string | null>(null)
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null)
  const [pendingPlanApproval, setPendingPlanApproval] = useState<PendingPlanApproval | null>(null)
  const activeConversationRef = useRef<string | null>(activeConversationId)
  const conversationMessagesRef = useRef<Map<string, Message[]>>(new Map())
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map())
  const onConversationUpdateRef = useRef(onConversationUpdate)
  const approvalResolverRef = useRef<((approved: boolean) => void) | null>(null)
  const planApprovalResolverRef = useRef<((approved: boolean) => void) | null>(null)
  const { settings } = useSettings()

  activeConversationRef.current = activeConversationId
  onConversationUpdateRef.current = onConversationUpdate
  const isLoading = !!activeConversationId && runningConversations.has(activeConversationId)

  const commitMessages = useCallback((conversationId: string, next: Message[]) => {
    conversationMessagesRef.current.set(conversationId, next)
    if (activeConversationRef.current === conversationId) setVisibleMessages(next)
    onConversationUpdateRef.current?.(conversationId, next)
  }, [])

  const setMessages = useCallback((next: Message[], conversationId?: string) => {
    const target = conversationId ?? activeConversationRef.current
    if (target) {
      conversationMessagesRef.current.set(target, next)
      if (conversationId) setVisibleMessages(next)
      else commitMessages(target, next)
    }
    else setVisibleMessages(next)
  }, [commitMessages])

  const setConversationRunning = useCallback((conversationId: string, running: boolean) => {
    setRunningConversations(previous => {
      const next = new Set(previous)
      if (running) next.add(conversationId)
      else next.delete(conversationId)
      return next
    })
  }, [])

  const respondToApproval = useCallback((approved: boolean) => {
    const resolve = approvalResolverRef.current
    approvalResolverRef.current = null
    setPendingApproval(null)
    resolve?.(approved)
  }, [])

  const respondToPlanApproval = useCallback((approved: boolean) => {
    const resolve = planApprovalResolverRef.current
    planApprovalResolverRef.current = null
    setPendingPlanApproval(null)
    resolve?.(approved)
  }, [])

  const addMessage = useCallback((content: string, role: Message['role'] = 'user', extra?: Partial<Message>, conversationId?: string): Message => {
    const message: Message = {
      id: uuidv4(),
      role,
      content,
      timestamp: Date.now(),
      ...extra,
    }
    const target = conversationId ?? activeConversationRef.current
    if (target) {
      const previous = conversationMessagesRef.current.get(target) ?? (activeConversationRef.current === target ? messages : [])
      commitMessages(target, [...previous, message])
    } else {
      setVisibleMessages(prev => [...prev, message])
    }
    return message
  }, [commitMessages, messages])

  const updateMessage = useCallback((id: string, updates: Partial<Message>, conversationId?: string) => {
    const target = conversationId ?? activeConversationRef.current
    if (!target) {
      setVisibleMessages(prev => prev.map(m => (m.id === id ? { ...m, ...updates } : m)))
      return
    }
    const previous = conversationMessagesRef.current.get(target) ?? []
    commitMessages(target, previous.map(m => (m.id === id ? { ...m, ...updates } : m)))
  }, [commitMessages])

  const clearMessages = useCallback(() => {
    respondToApproval(false)
    const target = activeConversationRef.current
    if (target) commitMessages(target, [])
    else setVisibleMessages([])
    setError(null)
  }, [commitMessages, respondToApproval])

  const stopGeneration = useCallback(() => {
    respondToApproval(false)
    const target = activeConversationRef.current
    const controller = target ? abortControllersRef.current.get(target) : undefined
    if (controller && target) {
      controller.abort()
      abortControllersRef.current.delete(target)
      setConversationRunning(target, false)
    }
  }, [respondToApproval, setConversationRunning])

  const runCompletion = useCallback(async (
    historyMessages: Message[],
    assistantId: string,
    overrides?: { model?: string; effort?: string; systemPromptOverride?: string },
    conversationId = activeConversationRef.current ?? '__draft__',
  ) => {
    setError(null)
    setConversationRunning(conversationId, true)

    const abortController = new AbortController()
    abortControllersRef.current.set(conversationId, abortController)

    const model = overrides?.model ?? settings.model
    const effort = overrides?.effort ?? settings.effort
    const systemPrompt = overrides?.systemPromptOverride ?? settings.systemPrompt

    const apiMessages = [...historyMessages]
    apiMessages.unshift({
      id: 'system-prompt',
      role: 'system',
      content: [systemPrompt, FILE_EXPORT_CAPABILITY].filter(Boolean).join('\n\n'),
      timestamp: Date.now()
    })

    let lastUsage: Message['usage']
    let fullContent = ''
    const userMessage = [...historyMessages].reverse().find(message => message.role === 'user')
    const attachmentMessage = [...historyMessages].reverse().find(
      message => message.role === 'user' && message.documentAttachments?.length
    )
    const requestedFormats = userMessage
      ? requestedDocumentFormats(
          userMessage.content,
          userMessage.documentAttachments?.length
            ? userMessage.documentAttachments
            : attachmentMessage?.documentAttachments,
        )
      : []

    const chatParams = {
      effort,
      temperature: settings.temperature,
      max_tokens: settings.maxTokens,
      top_p: settings.topP,
      presence_penalty: settings.presencePenalty,
      frequency_penalty: settings.frequencyPenalty,
      stop: settings.stop,
    }

    try {
      let responseModel = model
      const requestCompletion = async (requestModel: string) => {
        if (!settings.streaming) {
          return apiClient.chat(apiMessages, {
            signal: abortController.signal,
            ...chatParams,
            model: requestModel,
          })
        }
        return apiClient.chat(apiMessages, {
          signal: abortController.signal,
          ...chatParams,
          model: requestModel,
          onChunk: (chunk) => {
            if (chunk.usage) lastUsage = chunk.usage
            const hitCapacity = NVIDIA_CAPACITY_RE.test(chunk.content)
            updateMessage(assistantId, {
              // Document-edit preambles are not useful output. Clear them as
              // soon as a provider-capacity response arrives; the clean retry
              // below will replace the bubble with its own streamed content.
              content: hitCapacity
                ? (requestedFormats.length > 0 ? '' : withoutCapacityError(chunk.content))
                : chunk.content,
              model: requestModel,
              ...(chunk.finishReason ? { timestamp: Date.now() } : {}),
            }, conversationId)
          },
        })
      }

      fullContent = await requestCompletion(responseModel)
      if (NVIDIA_CAPACITY_RE.test(fullContent)) {
        responseModel = requestedFormats.length > 0
          ? DOCUMENT_FALLBACK_MODEL
          : model === GENERAL_FALLBACK_MODEL
            ? DOCUMENT_FALLBACK_MODEL
            : GENERAL_FALLBACK_MODEL
        lastUsage = undefined
        updateMessage(assistantId, {
          content: '',
          model: responseModel,
          error: false,
        }, conversationId)
        fullContent = await requestCompletion(responseModel)
      }

      if (NVIDIA_CAPACITY_RE.test(fullContent)) {
        throw new Error('NVIDIA models are temporarily at capacity after an automatic fallback attempt. Please retry shortly.')
      }

      updateMessage(assistantId, {
        content: fullContent,
        model: responseModel,
        timestamp: Date.now(),
      }, conversationId)
      if (requestedFormats.length > 0 && fullContent.trim() && userMessage) {
        const sourceMessage = attachmentMessage ?? userMessage
        const baseName = generatedDocumentBaseName(sourceMessage, userMessage.content)
        const generatedFiles = await Promise.all(
          requestedFormats.map(format => createGeneratedDocument(fullContent, baseName, format))
        )
        updateMessage(assistantId, { generatedFiles }, conversationId)
      }
      // Fall back to a rough token estimate when the server doesn't report usage.
      updateMessage(assistantId, {
        error: false,
        model: responseModel,
        usage: lastUsage,
      }, conversationId)
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        updateMessage(assistantId, { timestamp: Date.now() }, conversationId)
      } else {
        const errorMessage = (err as Error).message || 'An unexpected error occurred'
        updateMessage(assistantId, {
          content: errorMessage,
          error: true,
          model,
          timestamp: Date.now(),
        }, conversationId)
        setError(errorMessage)
      }
    } finally {
      setConversationRunning(conversationId, false)
      abortControllersRef.current.delete(conversationId)
    }
  }, [settings, setConversationRunning, updateMessage])

  const sendMessage = useCallback(async (content: string, images?: string[], opts?: { conversationId?: string; systemPromptOverride?: string; viaVoice?: boolean; documents?: ExtractedDocument[]; attachments?: DocumentAttachment[] }) => {
    if ((!content.trim() && !images?.length && !opts?.attachments?.length) || isLoading) return
    const conversationId = opts?.conversationId ?? activeConversationRef.current ?? '__draft__'
    const startingMessages = conversationMessagesRef.current.get(conversationId) ?? messages

    const documentContext = opts?.documents?.length
      ? [
          '[Extracted document content. Use every provided section to answer the user; do not claim that attachments are unreadable.]',
          ...opts.documents.map(document => [
            `\n--- ${document.name} ---`,
            document.truncated
              ? `[INCOMPLETE EXTRACTION: ${document.characters.toLocaleString()} characters were found, but only the bounded portion below is available.]`
              : `[COMPLETE TEXT EXTRACTION: ${document.characters.toLocaleString()} characters.]`,
            document.text,
          ].join('\n')),
        ].join('\n')
      : undefined

    let userMessage: Message
    if (images?.length) {
      if (isVisionModel(settings.model)) {
        // Vision model: attach images as multimodal parts (sent by the client).
        userMessage = addMessage(content, 'user', { images, imageMode: 'vision', documentContext, documentAttachments: opts?.attachments, viaVoice: opts?.viaVoice }, conversationId)
      } else {
        // Non-vision model: OCR the images to text and bake it into the prompt,
        // but keep the thumbnails for display.
        setConversationRunning(conversationId, true)
        let ocrText = ''
        try {
          ocrText = await ocrImages(images)
        } catch (err) {
          ocrText = `[OCR failed: ${(err as Error).message}]`
        }
        setConversationRunning(conversationId, false)
        const augmented = ocrText
          ? `${content}\n\n[Text extracted from image(s)]:\n${ocrText}`.trim()
          : content
        userMessage = addMessage(augmented, 'user', { images, imageMode: 'ocr', documentContext, documentAttachments: opts?.attachments, viaVoice: opts?.viaVoice }, conversationId)
      }
    } else {
      userMessage = addMessage(content, 'user', { documentContext, documentAttachments: opts?.attachments, viaVoice: opts?.viaVoice }, conversationId)
    }

    const assistantMessage = addMessage('', 'assistant', { viaVoice: opts?.viaVoice }, conversationId)
    // Enter the loading state immediately — the skill-match lookup below is
    // best-effort and must not delay the UI's "Dabba is working" feedback.
    setConversationRunning(conversationId, true)

    // Auto-apply a matching Skill's instructions when the user hasn't already
    // picked a mode/skill manually via the "+" menu — real trigger-based
    // Skills invocation instead of requiring a menu click every time.
    let effectiveOpts = opts
    if (!opts?.systemPromptOverride && content.trim()) {
      try {
        const matched = await apiClient.matchSkill(content)
        if (matched) effectiveOpts = { ...opts, systemPromptOverride: matched.instructions }
      } catch { /* best-effort — a lookup failure just means no auto-skill this turn */ }
    }

    await runCompletion([...startingMessages, userMessage], assistantMessage.id, effectiveOpts, conversationId)
  }, [messages, isLoading, addMessage, runCompletion, setConversationRunning, settings.model])

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
  const runAgentMode = useCallback(async (content: string, opts: { conversationId?: string; label: string; effort?: string; hint?: string; allowedTools?: string[]; viaVoice?: boolean; planMode?: boolean }) => {
    if (!content.trim() || isLoading) return
    const conversationId = opts.conversationId ?? activeConversationRef.current ?? '__draft__'

    const userMessage = addMessage(content, 'user', { viaVoice: opts.viaVoice }, conversationId)
    const assistantMessage = addMessage('', 'assistant', { agentActivity: { label: opts.label, steps: [], done: false }, viaVoice: opts.viaVoice }, conversationId)

    setError(null)
    setConversationRunning(conversationId, true)
    const abortController = new AbortController()
    abortControllersRef.current.set(conversationId, abortController)

    let textParts: string[] = []
    const steps: AgentStep[] = []

    const isResearch = opts.label === 'Research'
    const requestedFormats = requestedDocumentFormats(content)
    const exportHint = requestedFormats.length > 0
      ? `The Dabba client will convert your final response into ${requestedFormats.join(', ')} and attach the real file. ` +
        `Return the complete export data in the final response (use a markdown table for Excel). ` +
        `Do not call file_write or claim that a local file was created.`
      : ''
    // Research has a dedicated backend pipeline that gathers sources before
    // synthesis, so send the user's clean query instead of a UI-only hint.
    const instructionParts = [exportHint].filter(Boolean)
    const sendText = instructionParts.length
      ? `${instructionParts.join('\n\n')}\n\n${content}`
      : content

    try {
      await apiClient.streamAgent(sendText, {
        signal: abortController.signal,
        model: settings.model,
        effort: opts.effort ?? settings.effort,
        research: isResearch,
        conversationId,
        requirePlanApproval: !!(opts.planMode || settings.planModeDefault),
        permissionMode: settings.defaultPermissionMode,
        useToolSearch: settings.useToolSearch,
        maxSteps: settings.maxSteps,
        allowedTools: opts.allowedTools,
        contextCompactionThreshold: settings.contextCompactionThreshold,
        contextCompactionKeepRecent: settings.contextCompactionKeepRecent,
        onApproval: request => new Promise<boolean>(resolve => {
          // Keep the stream paused until the user makes an explicit choice in
          // the in-app dialog. Browser confirm() can be suppressed for async
          // responses and used to silently reject legitimate file exports.
          approvalResolverRef.current = resolve
          setPendingApproval(request)
        }),
        onPlanApproval: request => new Promise<boolean>(resolve => {
          planApprovalResolverRef.current = resolve
          setPendingPlanApproval(request)
        }),
        onEvent: (event) => {
          if (event.type === 'context_compacted') {
            const c = event.content as { summarized_entries?: number }
            steps.push({ tool: 'compact context', detail: `Summarized ${c?.summarized_entries ?? 0} earlier messages to free space`, success: true })
            updateMessage(assistantMessage.id, { agentActivity: { label: opts.label, steps: [...steps], done: false } }, conversationId)
          } else if (event.type === 'plan_step') {
            const c = event.content as { tool?: string; description?: string; status?: string; error?: string | null }
            steps.push({ tool: c?.tool ?? 'plan step', detail: c?.description ?? '', success: c?.status === 'succeeded' })
            updateMessage(assistantMessage.id, { agentActivity: { label: opts.label, steps: [...steps], done: false } }, conversationId)
          } else if (event.type === 'plan_summary') {
            const c = event.content as { summary?: string }
            textParts = [...textParts, String(c?.summary ?? '')]
            updateMessage(assistantMessage.id, { content: textParts.join('\n\n') }, conversationId)
          } else if (event.type === 'plan_denied') {
            textParts = [...textParts, '_Plan declined — continuing without it._']
            updateMessage(assistantMessage.id, { content: textParts.join('\n\n') }, conversationId)
          } else if (event.type === 'tool_call') {
            const c = event.content as { name?: string; arguments?: unknown }
            steps.push({ tool: c?.name ?? 'tool', detail: summarizeToolArgs(c?.arguments) })
            updateMessage(assistantMessage.id, { agentActivity: { label: opts.label, steps: [...steps], done: false } }, conversationId)
          } else if (event.type === 'tool_result') {
            const c = event.content as { tool?: string; success?: boolean; output?: unknown }
            // Best-effort match to the most recent step for this tool name.
            const idx = steps.map((s, i) => ({ s, i })).reverse().find(({ s }) => s.tool === c?.tool)?.i
            if (idx != null) steps[idx] = { ...steps[idx], success: c?.success }
            updateMessage(assistantMessage.id, { agentActivity: { label: opts.label, steps: [...steps], done: false } }, conversationId)
          } else if (event.type === 'text') {
            textParts = [...textParts, String(event.content ?? '')]
            updateMessage(assistantMessage.id, { content: textParts.join('\n\n') }, conversationId)
          } else if (event.type === 'question') {
            // ask_user ends the turn here (see agent_loop.py's stream_chat) —
            // render it like any other reply; the user's next message is
            // the answer, continuing the same conversation.
            const c = event.content as { question?: string; options?: string[] | null }
            const optionsText = c?.options?.length ? '\n' + c.options.map(o => `  • ${o}`).join('\n') : ''
            textParts = [...textParts, `❓ ${c?.question ?? ''}${optionsText}`]
            updateMessage(assistantMessage.id, { content: textParts.join('\n\n') }, conversationId)
          } else if (event.type === 'error') {
            throw new Error(String(event.content ?? 'Agent error'))
          }
        },
      })
      const finalContent = textParts.join('\n\n').trim()
      const generatedFiles = requestedFormats.length > 0 && finalContent
        ? await Promise.all(requestedFormats.map(format =>
            createGeneratedDocument(finalContent, generatedDocumentBaseName(userMessage, content), format)
          ))
        : undefined
      updateMessage(assistantMessage.id, {
        model: settings.model,
        timestamp: Date.now(),
        agentActivity: { label: opts.label, steps, done: true },
        ...(generatedFiles ? { generatedFiles } : {}),
      }, conversationId)
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        updateMessage(assistantMessage.id, { timestamp: Date.now(), agentActivity: { label: opts.label, steps, done: true } }, conversationId)
      } else {
        const errorMessage = (err as Error).message || `${opts.label} failed`
        updateMessage(assistantMessage.id, {
          content: errorMessage,
          error: true,
          timestamp: Date.now(),
          agentActivity: { label: opts.label, steps, done: true },
        }, conversationId)
        setError(errorMessage)
      }
    } finally {
      setConversationRunning(conversationId, false)
      abortControllersRef.current.delete(conversationId)
    }
  }, [isLoading, addMessage, setConversationRunning, updateMessage, settings.model, settings.effort, settings.planModeDefault, settings.defaultPermissionMode, settings.useToolSearch, settings.maxSteps, settings.contextCompactionThreshold, settings.contextCompactionKeepRecent])

  // Generates images from a prompt via /v1/images/generations (proxies to
  // whichever image-capable provider has a key configured — currently OpenAI).
  const generateImage = useCallback(async (prompt: string, requestedConversationId?: string) => {
    if (!prompt.trim() || isLoading) return
    const conversationId = requestedConversationId ?? activeConversationRef.current ?? '__draft__'

    addMessage(prompt, 'user', undefined, conversationId)
    const assistantMessage = addMessage('', 'assistant', { isGeneratingImage: true }, conversationId)

    setError(null)
    setConversationRunning(conversationId, true)
    const abortController = new AbortController()
    abortControllersRef.current.set(conversationId, abortController)

    try {
      const images = await apiClient.generateImages(prompt, { signal: abortController.signal })
      updateMessage(assistantMessage.id, {
        generatedImages: images,
        isGeneratingImage: false,
        timestamp: Date.now(),
      }, conversationId)
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        updateMessage(assistantMessage.id, { isGeneratingImage: false, timestamp: Date.now() }, conversationId)
      } else {
        const errorMessage = (err as Error).message || 'Image generation failed'
        updateMessage(assistantMessage.id, {
          content: errorMessage,
          error: true,
          isGeneratingImage: false,
          timestamp: Date.now(),
        }, conversationId)
        setError(errorMessage)
      }
    } finally {
      setConversationRunning(conversationId, false)
      abortControllersRef.current.delete(conversationId)
    }
  }, [isLoading, addMessage, setConversationRunning, updateMessage])

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
    runningConversationIds: [...runningConversations],
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
    pendingApproval,
    respondToApproval,
    pendingPlanApproval,
    respondToPlanApproval,
  }
}
