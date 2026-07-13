import type { ChatCompletionRequest, ChatCompletionResponse, StreamChunk, Message, ModelCatalog, TokenUsage, McpServer, Conversation } from '@/types'

async function responseError(response: Response, fallback: string): Promise<Error> {
  const text = await response.text().catch(() => '')
  if (!text) return new Error(fallback)

  try {
    const body = JSON.parse(text) as {
      detail?: unknown
      error?: { message?: unknown }
    }
    if (typeof body.error?.message === 'string') return new Error(body.error.message)
    if (typeof body.detail === 'string') return new Error(body.detail)
    if (Array.isArray(body.detail)) {
      const details = body.detail
        .map(item => typeof item?.msg === 'string' ? item.msg : '')
        .filter(Boolean)
        .join('; ')
      if (details) return new Error(details)
    }
  } catch {
    // Some proxies return plain-text errors instead of JSON.
  }

  return new Error(text.trim() || fallback)
}

export class ApiClient {
  private baseUrl: string
  private apiKey: string

  constructor(baseUrl = 'http://localhost:8080', apiKey = '') {
    this.baseUrl = baseUrl
    this.apiKey = apiKey
  }

  setBaseUrl(url: string) {
    this.baseUrl = url
  }

  setApiKey(key: string) {
    this.apiKey = key
  }

  private getHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`
    }
    return headers
  }

  private mapMessages(messages: Message[]): { role: string; content: unknown }[] {
    return messages.map(m => {
      // Vision messages carry images as OpenAI-format multimodal content parts.
      if (m.images?.length && m.imageMode === 'vision') {
        return {
          role: m.role,
          content: [
            ...(m.content ? [{ type: 'text', text: m.content }] : []),
            ...m.images.map(url => ({ type: 'image_url', image_url: { url } })),
          ],
        }
      }
      return { role: m.role, content: m.content }
    })
  }

  async executeCode(
    language: string,
    code: string,
    stdin = '',
    signal?: AbortSignal,
  ): Promise<{ language: string; exitCode: number | null; stdout: string; stderr: string; timedOut: boolean; truncated?: boolean; durationMs: number; phase?: 'compile' | 'run' }> {
    const response = await fetch(`${this.baseUrl}/v1/code/execute`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ language, code, stdin, timeout: 5 }),
      signal,
    })
    if (!response.ok) {
      const error = await responseError(response, `Execution failed (status ${response.status})`)
      if (response.status === 422 && language.toLowerCase() === 'java' && error.message.includes('Runtime not installed')) {
        throw new Error('Java runtime is not installed. Install the Java JDK, then restart the Dabba backend.')
      }
      throw error
    }
    return response.json()
  }

  /** Fetch the full model catalog from the Dabba agent endpoint (providers, tiers, key status). */
  async fetchModels(signal?: AbortSignal): Promise<ModelCatalog> {
    const response = await fetch(`${this.baseUrl}/v1/agent/models`, {
      headers: this.getHeaders(),
      signal,
    })
    if (!response.ok) {
      throw new Error(`Failed to load models (status ${response.status})`)
    }
    return response.json()
  }

  /** Fetch connected MCP servers and their tools. */
  async fetchMcpStatus(signal?: AbortSignal): Promise<{ servers: McpServer[] }> {
    const response = await fetch(`${this.baseUrl}/v1/mcp/status`, {
      headers: this.getHeaders(),
      signal,
    })
    if (!response.ok) {
      throw new Error(`Failed to load MCP status (status ${response.status})`)
    }
    return response.json()
  }

  /** Adds a new MCP connector to mcp_servers.json and connects it immediately. */
  async addMcpServer(input: { name: string; command: string; args?: string[]; env?: Record<string, string> }): Promise<void> {
    const response = await fetch(`${this.baseUrl}/v1/mcp/servers`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify(input),
    })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.detail ?? `Failed to add connector (status ${response.status})`)
    }
  }

  /** Removes an MCP connector from mcp_servers.json. */
  async deleteMcpServer(name: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/v1/mcp/servers/${encodeURIComponent(name)}`, {
      method: 'DELETE',
      headers: this.getHeaders(),
    })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.detail ?? `Failed to remove connector (status ${response.status})`)
    }
  }

  /** Which providers have an API key configured server-side — never the key values themselves. */
  async fetchProviderKeys(signal?: AbortSignal): Promise<{ provider: string; hasKey: boolean }[]> {
    const response = await fetch(`${this.baseUrl}/v1/agent/keys`, {
      headers: this.getHeaders(),
      signal,
    })
    if (!response.ok) {
      throw new Error(`Failed to load API key status (status ${response.status})`)
    }
    const data = await response.json()
    return data.providers ?? []
  }

  /** Sets a provider API key server-side — same effect as the CLI's `/keys set <provider> <key>`. */
  async setProviderKey(provider: string, key: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/v1/agent/keys`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ provider, key }),
    })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.error?.message ?? body?.detail ?? `Failed to save key (status ${response.status})`)
    }
  }

  async deleteProviderKey(provider: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/v1/agent/keys/${encodeURIComponent(provider)}`, {
      method: 'DELETE',
      headers: this.getHeaders(),
    })
    if (!response.ok && response.status !== 404) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.error?.message ?? body?.detail ?? `Failed to remove key (status ${response.status})`)
    }
  }

  /** Loads every conversation stored server-side for this user. */
  async fetchConversations(userId: string, signal?: AbortSignal): Promise<Conversation[]> {
    const response = await fetch(`${this.baseUrl}/v1/conversations?user_id=${encodeURIComponent(userId)}`, {
      headers: this.getHeaders(),
      signal,
    })
    if (!response.ok) {
      throw new Error(`Failed to load conversations (status ${response.status})`)
    }
    const data = await response.json()
    return data.conversations ?? []
  }

  /** Creates or updates one conversation server-side. */
  async saveConversationRemote(userId: string, conv: Conversation): Promise<void> {
    const response = await fetch(`${this.baseUrl}/v1/conversations/${encodeURIComponent(conv.id)}`, {
      method: 'PUT',
      headers: this.getHeaders(),
      body: JSON.stringify({
        id: conv.id,
        userId,
        title: conv.title,
        messages: conv.messages,
        createdAt: conv.createdAt,
        updatedAt: conv.updatedAt,
        pinned: !!conv.pinned,
        customTitle: !!conv.customTitle,
        projectId: conv.projectId ?? null,
      }),
    })
    if (!response.ok) {
      throw new Error(`Failed to save conversation (status ${response.status})`)
    }
  }

  async deleteConversationRemote(userId: string, id: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/v1/conversations/${encodeURIComponent(id)}?user_id=${encodeURIComponent(userId)}`, {
      method: 'DELETE',
      headers: this.getHeaders(),
    })
    if (!response.ok && response.status !== 404) {
      throw new Error(`Failed to delete conversation (status ${response.status})`)
    }
  }

  /**
   * Transcribes recorded audio to text via the server's Whisper endpoint.
   * Accepts whatever container the browser's MediaRecorder produced
   * (WebM/Opus, etc.) — the server decodes it with ffmpeg regardless of the
   * nominal filename, no client-side transcoding needed.
   */
  async transcribeAudio(audioBlob: Blob, opts?: { model?: string; signal?: AbortSignal }): Promise<string> {
    const buffer = await audioBlob.arrayBuffer()
    const base64 = btoa(Array.from(new Uint8Array(buffer), b => String.fromCharCode(b)).join(''))

    const response = await fetch(`${this.baseUrl}/v1/transcribe`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ audio_base64: base64, model: opts?.model ?? 'base' }),
      signal: opts?.signal,
    })
    if (!response.ok) {
      throw await responseError(response, `Transcription request failed (status ${response.status})`)
    }
    const data = await response.json()
    if (data.error) throw new Error(data.error)
    return (data.text ?? '').trim()
  }

  /** Synthesizes text to speech via the server's offline Piper TTS endpoint. Returns a playable audio Blob. */
  async synthesizeSpeech(text: string, opts?: { voice?: string; signal?: AbortSignal }): Promise<Blob> {
    const response = await fetch(`${this.baseUrl}/v1/speech`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ text, voice: opts?.voice }),
      signal: opts?.signal,
    })
    if (!response.ok) {
      throw await responseError(response, `Speech synthesis failed (status ${response.status})`)
    }
    return response.blob()
  }

  /** Generate images from a text prompt. Returns data URLs (works for both b64_json and url responses). */
  async generateImages(prompt: string, opts?: { size?: string; n?: number; signal?: AbortSignal }): Promise<string[]> {
    const response = await fetch(`${this.baseUrl}/v1/images/generations`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ prompt, size: opts?.size ?? '1024x1024', n: opts?.n ?? 1 }),
      signal: opts?.signal,
    })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.error?.message ?? body?.detail ?? `Image generation failed (status ${response.status})`)
    }
    const data = await response.json()
    return (data.data ?? []).map((item: { b64_json?: string; url?: string }) =>
      item.b64_json ? `data:image/png;base64,${item.b64_json}` : (item.url ?? '')
    ).filter(Boolean)
  }

  /**
   * Runs one turn of the Dabba agent loop (POST /v1/agent) — the same
   * tool-using loop the VS Code extension drives, including real web search.
   * Unlike chat(), this endpoint keeps its own conversation memory
   * server-side; only the latest message is sent, not the full history.
   */
  async streamAgent(
    message: string,
    options: {
      signal?: AbortSignal
      model?: string
      effort?: string
      onEvent: (event: { type: string; content: unknown }) => void
    }
  ): Promise<void> {
    const response = await fetch(`${this.baseUrl}/v1/agent`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({
        message,
        model: options.model,
        effort: options.effort,
        permission_mode: 'auto', // headless web UI — never pause for tool approval
      }),
      signal: options.signal,
    })

    if (!response.ok) {
      const errorText = await response.text().catch(() => 'Unknown error')
      throw new Error(`Agent error ${response.status}: ${errorText}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('Response body is not readable')

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data: ')) continue
        try {
          options.onEvent(JSON.parse(trimmed.slice(6)))
        } catch {
          // skip malformed SSE payloads
        }
      }
    }
  }

  async chat(
    messages: Message[],
    options?: {
      signal?: AbortSignal
      onChunk?: (chunk: StreamChunk) => void
      model?: string
      temperature?: number
      max_tokens?: number
      effort?: string
      top_p?: number
      presence_penalty?: number
      frequency_penalty?: number
      stop?: string[]
    }
  ): Promise<string> {
    const body: ChatCompletionRequest = {
      model: options?.model || 'default',
      messages: this.mapMessages(messages),
      stream: !!options?.onChunk,
      temperature: options?.temperature ?? 0.7,
      max_tokens: options?.max_tokens,
      ...(options?.effort ? { effort: options.effort } : {}),
      ...(options?.top_p != null ? { top_p: options.top_p } : {}),
      ...(options?.presence_penalty ? { presence_penalty: options.presence_penalty } : {}),
      ...(options?.frequency_penalty ? { frequency_penalty: options.frequency_penalty } : {}),
      ...(options?.stop && options.stop.length ? { stop: options.stop } : {}),
    }

    if (options?.onChunk) {
      return this.streamChat(body, options.onChunk, options.signal)
    }

    return this.nonStreamingChat(body, options?.signal)
  }

  private async nonStreamingChat(
    body: ChatCompletionRequest,
    signal?: AbortSignal
  ): Promise<string> {
    const response = await fetch(`${this.baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ ...body, stream: false }),
      signal,
    })

    if (!response.ok) {
      const errorText = await response.text().catch(() => 'Unknown error')
      throw new Error(`API error ${response.status}: ${errorText}`)
    }

    const data: ChatCompletionResponse = await response.json()
    return data.choices[0]?.message?.content ?? ''
  }

  private async streamChat(
    body: ChatCompletionRequest,
    onChunk: (chunk: StreamChunk) => void,
    signal?: AbortSignal
  ): Promise<string> {
    const response = await fetch(`${this.baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ ...body, stream: true }),
      signal,
    })

    if (!response.ok) {
      const errorText = await response.text().catch(() => 'Unknown error')
      throw new Error(`API error ${response.status}: ${errorText}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('Response body is not readable')

    const decoder = new TextDecoder()
    let buffer = ''
    let fullContent = ''
    let usage: TokenUsage | undefined

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || !trimmed.startsWith('data: ')) continue

          const data = trimmed.slice(6)
          if (data === '[DONE]') continue

          try {
            const parsed = JSON.parse(data)
            const delta = parsed.choices?.[0]?.delta?.content ?? ''
            const finishReason = parsed.choices?.[0]?.finish_reason ?? null

            // Some servers emit a trailing usage object on the final SSE event.
            if (parsed.usage) {
              usage = {
                promptTokens: parsed.usage.prompt_tokens ?? 0,
                completionTokens: parsed.usage.completion_tokens ?? 0,
                totalTokens: parsed.usage.total_tokens ?? 0,
              }
            }

            if (delta) {
              fullContent += delta
              onChunk({ content: fullContent, finishReason, usage })
            } else if (finishReason) {
              onChunk({ content: fullContent, finishReason, usage })
            }
          } catch {
            // skip malformed JSON chunks
          }
        }
      }
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        onChunk({ content: fullContent, finishReason: 'stop' })
      }
      throw error
    }

    return fullContent
  }
}

export const apiClient = new ApiClient()
