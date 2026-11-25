import type { ChatCompletionRequest, ChatCompletionResponse, StreamChunk, Message, ModelCatalog, TokenUsage, McpServer, Conversation, UploadedFile, ExtractedDocument, CoworkItem, CoworkStatus, CoworkRun, CoworkSubtask, CoworkSchedule, AgentDefinition, Skill, DirectoryListing, ScheduledSkill, ScheduledSkillRun, PlatformTask, PlatformTaskEvent, AgentHook, HookEvent, HookRun } from '@/types'

export const DEFAULT_API_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '')

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

/** How long a shared read (models, skills) is reused before refetching. */
const READ_CACHE_TTL_MS = 30_000

/** Let one caller stop waiting on a shared promise without cancelling it for the others. */
function withAbort<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise
  if (signal.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'))
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(new DOMException('Aborted', 'AbortError'))
    signal.addEventListener('abort', onAbort, { once: true })
    promise.then(
      value => { signal.removeEventListener('abort', onAbort); resolve(value) },
      error => { signal.removeEventListener('abort', onAbort); reject(error) },
    )
  })
}

export class ApiClient {
  private baseUrl: string
  private apiKey: string
  private sessionToken = localStorage.getItem('dabba-session-token') ?? ''
  // Several components request the same read-only data on one page load
  // (the model catalog 3x, skills 2x). Concurrent callers share one in-flight
  // request and reuse its result for READ_CACHE_TTL_MS.
  private readCache = new Map<string, { at: number; promise: Promise<unknown> }>()

  constructor(baseUrl = DEFAULT_API_URL, apiKey = '') {
    this.baseUrl = baseUrl
    this.apiKey = apiKey
  }

  setBaseUrl(url: string) {
    this.baseUrl = url.replace(/\/+$/, '')
  }

  setApiKey(key: string) {
    this.apiKey = key
  }

  /**
   * Shared, short-lived cache for idempotent GETs. The key includes the
   * server, session and API key so a different user or server never sees
   * another's cached data. Failed requests are dropped so the next call retries.
   */
  private cachedRead<T>(name: string, load: () => Promise<T>, opts: { signal?: AbortSignal; force?: boolean } = {}): Promise<T> {
    const key = `${name}|${this.baseUrl}|${this.sessionToken}|${this.apiKey}`
    const hit = this.readCache.get(key)
    if (!opts.force && hit && Date.now() - hit.at < READ_CACHE_TTL_MS) {
      return withAbort(hit.promise as Promise<T>, opts.signal)
    }
    const promise = load()
    const entry = { at: Date.now(), promise }
    this.readCache.set(key, entry)
    promise.catch(() => { if (this.readCache.get(key) === entry) this.readCache.delete(key) })
    return withAbort(promise, opts.signal)
  }

  /** Drop cached reads for one resource (call after writes that change it). */
  invalidateReadCache(name: string) {
    for (const key of this.readCache.keys()) {
      if (key.startsWith(`${name}|`)) this.readCache.delete(key)
    }
  }

  setSessionToken(token: string) {
    this.sessionToken = token
    if (token) localStorage.setItem('dabba-session-token', token)
    else localStorage.removeItem('dabba-session-token')
  }

  private getHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`
    }
    if (this.sessionToken) {
      headers['X-Dabba-Session'] = this.sessionToken
    }
    return headers
  }

  private getPlatformHeaders(): Record<string, string> {
    return {
      'Content-Type': 'application/json',
      ...(this.sessionToken ? { Authorization: `Bearer ${this.sessionToken}` } : {}),
    }
  }

  async signup(name: string, email: string, password: string): Promise<{ user: PlatformUser; token: string }> {
    let response: Response
    try {
      response = await fetch(`${this.baseUrl}/v1/platform/identity/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password }),
      })
    } catch {
      throw new Error('Cannot reach the Dabba backend. Start the server and try again.')
    }
    if (!response.ok) throw await responseError(response, 'Signup failed')
    const data = await response.json() as { user: PlatformUser; token: string }
    this.setSessionToken(data.token)
    return data
  }

  async login(email: string, password: string): Promise<{ user: PlatformUser; token: string }> {
    let response: Response
    try {
      response = await fetch(`${this.baseUrl}/v1/platform/identity/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
    } catch {
      throw new Error('Cannot reach the Dabba backend. Start the server and try again.')
    }
    if (!response.ok) throw await responseError(response, 'Login failed')
    const data = await response.json() as { user: PlatformUser; token: string }
    this.setSessionToken(data.token)
    return data
  }

  /** Free prompts left for a signed-out visitor (server-enforced). */
  async guestStatus(guestId: string, signal?: AbortSignal): Promise<{ available: boolean; remaining: number; limit: number }> {
    const response = await fetch(`${this.baseUrl}/v1/guest/status?guestId=${encodeURIComponent(guestId)}`, { signal })
    if (!response.ok) throw await responseError(response, 'Could not check free prompts')
    return response.json()
  }

  /**
   * Send a guest prompt and stream the reply. The server sends
   * `{"delta": text}` events as the reply is generated, then
   * `{"done": true, "remaining": n}` or `{"error": ..., "remaining": n}`;
   * comment lines are keepalives. A 429 means the free prompts are used up.
   */
  async guestChat(
    guestId: string,
    messages: Array<{ role: 'user' | 'assistant'; content: string }>,
    onDelta: (text: string) => void,
    signal?: AbortSignal,
  ): Promise<{ error?: string; remaining: number; limitReached?: boolean }> {
    let response: Response
    try {
      response = await fetch(`${this.baseUrl}/v1/guest/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ guestId, messages }),
        signal,
      })
    } catch (err) {
      if ((err as Error).name === 'AbortError') throw err
      throw new Error('Cannot reach Dabba right now. Check your connection and try again.')
    }
    if (response.status === 429) return { remaining: 0, limitReached: true }
    if (!response.ok || !response.body) throw await responseError(response, 'Dabba couldn\'t answer just now. Try again in a moment.')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let result: { error?: string; remaining: number } | null = null
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE events are separated by a blank line; keep any partial event.
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const part of parts) {
        const line = part.split('\n').find(row => row.startsWith('data: '))
        if (!line) continue // keepalive comment
        const event = JSON.parse(line.slice('data: '.length)) as { delta?: string; done?: boolean; error?: string; remaining?: number }
        if (event.delta) onDelta(event.delta)
        else if (event.done || event.error) result = { error: event.error, remaining: event.remaining ?? 0 }
      }
    }
    if (!result) throw new Error('Dabba couldn\'t answer just now. Try again in a moment.')
    return result
  }

  async currentUser(signal?: AbortSignal): Promise<PlatformUser | null> {
    if (!this.sessionToken) return null
    const response = await fetch(`${this.baseUrl}/v1/platform/identity/me`, {
      headers: this.getPlatformHeaders(),
      signal,
    })
    if (response.status === 401) {
      this.setSessionToken('')
      return null
    }
    if (!response.ok) throw await responseError(response, 'Could not restore your session')
    return response.json()
  }

  async logout(): Promise<void> {
    if (this.sessionToken) {
      await fetch(`${this.baseUrl}/v1/platform/identity/logout`, {
        method: 'POST',
        headers: this.getPlatformHeaders(),
      }).catch(() => undefined)
    }
    this.setSessionToken('')
  }

  private async platformRequest<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response
    try {
      response = await fetch(`${this.baseUrl}/v1/platform${path}`, {
        ...init,
        headers: { ...this.getPlatformHeaders(), ...(init?.headers ?? {}) },
      })
    } catch {
      throw new Error('Cannot reach the Dabba backend. Check that the server is running.')
    }
    if (!response.ok) {
      const fallback = response.status >= 500
        ? 'The Dabba backend could not complete this request. Please retry.'
        : `Platform request failed (${response.status})`
      throw await responseError(response, fallback)
    }
    if (response.status === 204) return undefined as T
    return response.json()
  }

  async listCoworkItems(status?: CoworkStatus): Promise<CoworkItem[]> {
    const data = await this.platformRequest<{ items: CoworkItem[] }>(
      `/cowork/items${status ? `?status=${encodeURIComponent(status)}` : ''}`,
    )
    return data.items
  }

  createCoworkItem(input: Partial<CoworkItem> & { title: string }): Promise<CoworkItem> {
    return this.platformRequest('/cowork/items', { method: 'POST', body: JSON.stringify(input) })
  }

  updateCoworkItem(id: string, changes: Partial<CoworkItem>): Promise<CoworkItem> {
    return this.platformRequest(`/cowork/items/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(changes),
    })
  }

  deleteCoworkItem(id: string): Promise<void> {
    return this.platformRequest(`/cowork/items/${encodeURIComponent(id)}`, { method: 'DELETE' })
  }

  async listCoworkRuns(itemId: string): Promise<CoworkRun[]> {
    const data = await this.platformRequest<{ runs: CoworkRun[] }>(
      `/cowork/items/${encodeURIComponent(itemId)}/runs`,
    )
    return data.runs
  }

  runCoworkItem(itemId: string, input: { mode: 'safe' | 'agent'; workspacePath?: string; model?: string; effort?: string }): Promise<CoworkRun> {
    return this.platformRequest(`/cowork/items/${encodeURIComponent(itemId)}/runs`, {
      method: 'POST', body: JSON.stringify(input),
    })
  }

  cancelCoworkRun(runId: string): Promise<CoworkRun> {
    return this.platformRequest(`/cowork/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' })
  }

  async listCoworkSubtasks(itemId: string): Promise<CoworkSubtask[]> {
    const data = await this.platformRequest<{ subtasks: CoworkSubtask[] }>(
      `/cowork/items/${encodeURIComponent(itemId)}/subtasks`,
    )
    return data.subtasks
  }

  addCoworkSubtask(itemId: string, title: string): Promise<CoworkSubtask> {
    return this.platformRequest(`/cowork/items/${encodeURIComponent(itemId)}/subtasks`, {
      method: 'POST', body: JSON.stringify({ title }),
    })
  }

  updateCoworkSubtask(subtaskId: string, changes: { title?: string; status?: 'pending' | 'done' }): Promise<CoworkSubtask> {
    return this.platformRequest(`/cowork/subtasks/${encodeURIComponent(subtaskId)}`, {
      method: 'PATCH', body: JSON.stringify(changes),
    })
  }

  deleteCoworkSubtask(subtaskId: string): Promise<void> {
    return this.platformRequest(`/cowork/subtasks/${encodeURIComponent(subtaskId)}`, { method: 'DELETE' })
  }

  async listCoworkSchedules(itemId: string): Promise<CoworkSchedule[]> {
    const data = await this.platformRequest<{ schedules: CoworkSchedule[] }>(
      `/cowork/items/${encodeURIComponent(itemId)}/schedules`,
    )
    return data.schedules
  }

  createCoworkSchedule(itemId: string, input: Partial<Pick<CoworkSchedule, 'cadence' | 'intervalMinutes' | 'timeOfDay' | 'weekdays' | 'mode' | 'workspacePath' | 'model' | 'effort' | 'enabled'>>): Promise<CoworkSchedule> {
    return this.platformRequest(`/cowork/items/${encodeURIComponent(itemId)}/schedules`, {
      method: 'POST', body: JSON.stringify(input),
    })
  }

  updateCoworkSchedule(scheduleId: string, changes: Partial<Pick<CoworkSchedule, 'cadence' | 'intervalMinutes' | 'timeOfDay' | 'weekdays' | 'mode' | 'workspacePath' | 'model' | 'effort' | 'enabled'>>): Promise<CoworkSchedule> {
    return this.platformRequest(`/cowork/schedules/${encodeURIComponent(scheduleId)}`, {
      method: 'PATCH', body: JSON.stringify(changes),
    })
  }

  deleteCoworkSchedule(scheduleId: string): Promise<void> {
    return this.platformRequest(`/cowork/schedules/${encodeURIComponent(scheduleId)}`, { method: 'DELETE' })
  }

  browseWorkspaceDirectories(path?: string): Promise<DirectoryListing> {
    return this.platformRequest(
      `/filesystem/directories${path ? `?path=${encodeURIComponent(path)}` : ''}`,
    )
  }

  pickWorkspaceDirectory(initialPath?: string): Promise<{ path: string | null; cancelled: boolean }> {
    return this.platformRequest('/filesystem/pick-directory', {
      method: 'POST', body: JSON.stringify({ initialPath: initialPath || null }),
    })
  }

  async publishArtifact(name: string, content: string, mediaType: string, title: string): Promise<{ slug: string; title: string; url: string }> {
    // btoa is ASCII-only; encode as UTF-8 bytes first so non-ASCII artifact content round-trips correctly.
    const bytes = new TextEncoder().encode(content)
    const base64 = btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''))
    const created = await this.platformRequest<{ id: string }>('/artifacts', {
      method: 'POST', body: JSON.stringify({ name, data: base64, mediaType }),
    })
    const published = await this.platformRequest<{ slug: string; title: string; url: string }>(
      `/artifacts/${encodeURIComponent(created.id)}/publish`,
      { method: 'POST', body: JSON.stringify({ title }) },
    )
    return { ...published, url: `${this.baseUrl}${published.url}` }
  }

  async listPublishedArtifacts(): Promise<Array<{ slug: string; title: string; artifactId: string; createdAt: number }>> {
    const data = await this.platformRequest<{ published: Array<{ slug: string; title: string; artifactId: string; createdAt: number }> }>('/artifacts/published')
    return data.published
  }

  unpublishArtifact(slug: string): Promise<void> {
    return this.platformRequest(`/artifacts/publish/${encodeURIComponent(slug)}`, { method: 'DELETE' })
  }

  async listMemories(scope?: string): Promise<Array<{ id: string; scope: string; key: string; content: string; updatedAt: number }>> {
    const query = scope ? `?scope=${encodeURIComponent(scope)}` : ''
    const data = await this.platformRequest<{ memories: Array<{ id: string; scope: string; key: string; content: string; updatedAt: number }> }>(`/memory${query}`)
    return data.memories
  }

  saveMemory(scope: string, key: string, content: string): Promise<{ scope: string; key: string; content: string; updatedAt: number }> {
    return this.platformRequest('/memory', { method: 'PUT', body: JSON.stringify({ scope, key, content }) })
  }

  deleteMemory(memoryId: string): Promise<void> {
    return this.platformRequest(`/memory/${encodeURIComponent(memoryId)}`, { method: 'DELETE' })
  }

  async listSkills(opts: { force?: boolean } = {}): Promise<Skill[]> {
    const data = await this.cachedRead('skills', () => this.platformRequest<{ skills: Skill[] }>('/skills'), opts)
    return data.skills
  }

  async createSkillPackage(input: { name: string; instructions: string; description?: string; script?: string }): Promise<Skill> {
    const skill = await this.platformRequest<Skill>('/skills', { method: 'POST', body: JSON.stringify(input) })
    this.invalidateReadCache('skills')
    return skill
  }

  async importSkillPackage(input: { url?: string; content?: string }): Promise<Skill> {
    const skill = await this.platformRequest<Skill>('/skills/import', { method: 'POST', body: JSON.stringify(input) })
    this.invalidateReadCache('skills')
    return skill
  }

  async deleteSkillPackage(id: string): Promise<void> {
    await this.platformRequest(`/skills/${encodeURIComponent(id)}`, { method: 'DELETE' })
    this.invalidateReadCache('skills')
  }

  async matchSkill(message: string): Promise<Skill | null> {
    const data = await this.platformRequest<{ skill: Skill | null }>('/skills/match', {
      method: 'POST', body: JSON.stringify({ message }),
    })
    return data.skill
  }

  async listAgentDefinitions(): Promise<AgentDefinition[]> {
    const data = await this.platformRequest<{ definitions: AgentDefinition[] }>('/agent-definitions')
    return data.definitions
  }

  createAgentDefinition(input: { name: string; systemPrompt: string; description?: string; allowedTools?: string[]; model?: string; effort?: string }): Promise<AgentDefinition> {
    return this.platformRequest('/agent-definitions', { method: 'POST', body: JSON.stringify(input) })
  }

  updateAgentDefinition(id: string, changes: Partial<Pick<AgentDefinition, 'name' | 'description' | 'systemPrompt' | 'allowedTools' | 'model' | 'effort'>>): Promise<AgentDefinition> {
    return this.platformRequest(`/agent-definitions/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(changes) })
  }

  deleteAgentDefinition(id: string): Promise<void> {
    return this.platformRequest(`/agent-definitions/${encodeURIComponent(id)}`, { method: 'DELETE' })
  }

  dispatchAgentDefinitions(assignments: Record<string, { definitionId: string; prompt: string }>, workspacePath?: string): Promise<Record<string, { success: boolean; result?: string; error?: string }>> {
    return this.platformRequest('/agent-definitions/dispatch', {
      method: 'POST', body: JSON.stringify({ assignments, workspacePath }),
    })
  }

  async runAgentDefinitionPipeline(
    stages: Array<{ definitionId: string; promptTemplate: string; outputSchema?: Record<string, unknown> }>,
    initialInput = '',
    workspacePath?: string,
  ): Promise<Array<{ role: string; success: boolean; result?: unknown; error?: string }>> {
    const data = await this.platformRequest<{ results: Array<{ role: string; success: boolean; result?: unknown; error?: string }> }>(
      '/agent-definitions/pipeline',
      { method: 'POST', body: JSON.stringify({ stages, initialInput, workspacePath }) },
    )
    return data.results
  }

  async listScheduledSkills(): Promise<ScheduledSkill[]> {
    const data = await this.platformRequest<{ schedules: ScheduledSkill[] }>('/scheduled-skills')
    return data.schedules
  }

  createScheduledSkill(input: Omit<ScheduledSkill, 'id' | 'createdAt' | 'updatedAt' | 'lastRunAt' | 'lastStatus'>): Promise<ScheduledSkill> {
    return this.platformRequest('/scheduled-skills', { method: 'POST', body: JSON.stringify(input) })
  }

  updateScheduledSkill(id: string, changes: Partial<ScheduledSkill>): Promise<ScheduledSkill> {
    return this.platformRequest(`/scheduled-skills/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(changes),
    })
  }

  deleteScheduledSkill(id: string): Promise<void> {
    return this.platformRequest(`/scheduled-skills/${encodeURIComponent(id)}`, { method: 'DELETE' })
  }

  runScheduledSkill(id: string): Promise<ScheduledSkillRun> {
    return this.platformRequest(`/scheduled-skills/${encodeURIComponent(id)}/run`, { method: 'POST' })
  }

  async listScheduledSkillRuns(): Promise<ScheduledSkillRun[]> {
    const data = await this.platformRequest<{ runs: ScheduledSkillRun[] }>('/scheduled-skills/runs')
    return data.runs
  }

  async listPlatformTasks(status?: PlatformTask['status']): Promise<PlatformTask[]> {
    const data = await this.platformRequest<{ tasks: PlatformTask[] }>(
      `/tasks${status ? `?status=${encodeURIComponent(status)}` : ''}`,
    )
    return data.tasks
  }

  getPlatformTask(id: string): Promise<PlatformTask> {
    return this.platformRequest(`/tasks/${encodeURIComponent(id)}`)
  }

  async listPlatformTaskEvents(id: string): Promise<PlatformTaskEvent[]> {
    const data = await this.platformRequest<{ events: PlatformTaskEvent[] }>(
      `/tasks/${encodeURIComponent(id)}/events`,
    )
    return data.events
  }

  cancelPlatformTask(id: string): Promise<PlatformTask> {
    return this.platformRequest(`/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
  }

  resumePlatformTask(id: string): Promise<PlatformTask> {
    return this.platformRequest(`/tasks/${encodeURIComponent(id)}/resume`, { method: 'POST' })
  }

  private async hooksRequest<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}/v1/hooks${path}`, {
      ...init,
      headers: { ...this.getHeaders(), ...(init?.headers ?? {}) },
    })
    if (!response.ok) throw await responseError(response, `Hooks request failed (${response.status})`)
    if (response.status === 204) return undefined as T
    return response.json()
  }

  async listHooks(): Promise<{ hooks: AgentHook[]; events: HookEvent[] }> {
    return this.hooksRequest('')
  }

  createHook(input: { event: HookEvent; command: string; matcher?: string; timeout?: number; enabled?: boolean }): Promise<AgentHook> {
    return this.hooksRequest('', { method: 'POST', body: JSON.stringify(input) })
  }

  updateHook(id: string, changes: Partial<Pick<AgentHook, 'event' | 'command' | 'matcher' | 'timeout' | 'enabled'>>): Promise<AgentHook> {
    return this.hooksRequest(`/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(changes) })
  }

  deleteHook(id: string): Promise<void> {
    return this.hooksRequest(`/${encodeURIComponent(id)}`, { method: 'DELETE' })
  }

  async listHookRuns(limit = 50): Promise<HookRun[]> {
    const data = await this.hooksRequest<{ runs: HookRun[] }>(`/runs?limit=${limit}`)
    return data.runs
  }

  async approveAgentCall(callId: string, approved: boolean): Promise<void> {
    const response = await fetch(`${this.baseUrl}/v1/agent/approve`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ call_id: callId, approved }),
    })
    if (!response.ok) throw await responseError(response, 'Could not send the approval decision')
  }

  async listBackgroundProcesses(): Promise<Array<{ process_id: string; command: string; pid: number; status: string; uptime_seconds: number }>> {
    const response = await fetch(`${this.baseUrl}/v1/agent/processes`, { headers: this.getHeaders() })
    if (!response.ok) throw await responseError(response, 'Could not list background processes')
    const data = await response.json()
    return data.processes ?? []
  }

  async releaseAgentConversation(conversationId: string): Promise<void> {
    await fetch(`${this.baseUrl}/v1/agent/conversations/${encodeURIComponent(conversationId)}`, {
      method: 'DELETE',
      headers: this.getHeaders(),
    }).catch(() => undefined)
  }

  private mapMessages(messages: Message[]): { role: string; content: unknown }[] {
    return messages.map(m => {
      // Vision messages carry images as OpenAI-format multimodal content parts.
      if (m.images?.length && m.imageMode === 'vision') {
        const textContent = m.documentContext
          ? `${m.content}\n\n${m.documentContext}`.trim()
          : m.content
        return {
          role: m.role,
          content: [
            ...(textContent ? [{ type: 'text', text: textContent }] : []),
            ...m.images.map(url => ({ type: 'image_url', image_url: { url } })),
          ],
        }
      }
      const content = m.documentContext
        ? `${m.content}\n\n${m.documentContext}`.trim()
        : m.content
      return { role: m.role, content }
    })
  }

  async extractDocuments(files: UploadedFile[], signal?: AbortSignal): Promise<ExtractedDocument[]> {
    if (files.every(file => file.file)) {
      const form = new FormData()
      for (const file of files) form.append('files', file.file as File, file.name)
      const headers = this.getHeaders()
      // The browser must add the multipart boundary itself.
      delete headers['Content-Type']
      const response = await fetch(`${this.baseUrl}/v1/documents/extract-upload`, {
        method: 'POST',
        headers,
        body: form,
        signal,
      })
      if (!response.ok) {
        if (response.status === 404) {
          throw new Error(
            'Large-file uploads require the updated Dabba backend. Rebuild and restart the server, then try again.',
          )
        }
        throw await responseError(response, `Document extraction failed (status ${response.status})`)
      }
      const data = await response.json() as { documents?: ExtractedDocument[] }
      return data.documents ?? []
    }

    // Compatibility path for attachments restored from older in-memory state.
    const payload = files.map(file => {
      if (!file.dataUrl) throw new Error(`Attachment "${file.name}" has no readable data.`)
      return { name: file.name, data_url: file.dataUrl }
    })
    const response = await fetch(`${this.baseUrl}/v1/documents/extract`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ files: payload }),
      signal,
    })
    if (!response.ok) {
      throw await responseError(response, `Document extraction failed (status ${response.status})`)
    }
    const data = await response.json() as { documents?: ExtractedDocument[] }
    return data.documents ?? []
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
  async fetchModels(signal?: AbortSignal, opts: { force?: boolean } = {}): Promise<ModelCatalog> {
    // No per-caller signal on the shared request: one component unmounting
    // must not cancel the fetch other components are waiting on.
    return this.cachedRead('models', async () => {
      const response = await fetch(`${this.baseUrl}/v1/agent/models`, { headers: this.getHeaders() })
      if (!response.ok) {
        throw new Error(`Failed to load models (status ${response.status})`)
      }
      return response.json() as Promise<ModelCatalog>
    }, { signal, force: opts.force })
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
    this.invalidateReadCache('models')
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
    this.invalidateReadCache('models')
  }

  /**
   * Lightweight sidebar list: metadata and messageCount, no message bodies.
   * Entries come back with `messages: []` and `messagesLoaded: false`;
   * load a chat's messages with fetchConversation().
   */
  async fetchConversations(userId: string, signal?: AbortSignal): Promise<Conversation[]> {
    const response = await fetch(`${this.baseUrl}/v1/conversations?user_id=${encodeURIComponent(userId)}&include_messages=false`, {
      headers: this.getPlatformHeaders(),
      signal,
    })
    if (!response.ok) {
      throw new Error(`Failed to load conversations (status ${response.status})`)
    }
    const data = await response.json() as { conversations?: Array<Omit<Conversation, 'messages'> & { messages?: Message[] }> }
    return (data.conversations ?? []).map(summary => ({
      ...summary,
      messages: summary.messages ?? [],
      messagesLoaded: Array.isArray(summary.messages),
    }))
  }

  /** One full conversation with its messages (only the owner can read it). */
  async fetchConversation(id: string, signal?: AbortSignal): Promise<Conversation> {
    const response = await fetch(`${this.baseUrl}/v1/conversations/${encodeURIComponent(id)}`, {
      headers: this.getPlatformHeaders(),
      signal,
    })
    if (!response.ok) {
      throw new Error(`Failed to load conversation (status ${response.status})`)
    }
    const conversation = await response.json() as Conversation
    return { ...conversation, messagesLoaded: true, messageCount: conversation.messages.length }
  }

  /** Creates or updates one conversation server-side. */
  async saveConversationRemote(userId: string, conv: Conversation, opts: { keepalive?: boolean } = {}): Promise<void> {
    const body = JSON.stringify({
      id: conv.id,
      userId,
      title: conv.title,
      messages: conv.messages,
      createdAt: conv.createdAt,
      updatedAt: conv.updatedAt,
      pinned: !!conv.pinned,
      customTitle: !!conv.customTitle,
      projectId: conv.projectId ?? null,
    })
    const response = await fetch(`${this.baseUrl}/v1/conversations/${encodeURIComponent(conv.id)}`, {
      method: 'PUT',
      headers: this.getPlatformHeaders(),
      body,
      // keepalive lets a save finish while the tab closes, but browsers cap
      // keepalive bodies at 64 KB, so only use it for small payloads.
      keepalive: opts.keepalive && body.length < 60_000,
    })
    if (!response.ok) {
      throw new Error(`Failed to save conversation (status ${response.status})`)
    }
  }

  async deleteConversationRemote(userId: string, id: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/v1/conversations/${encodeURIComponent(id)}?user_id=${encodeURIComponent(userId)}`, {
      method: 'DELETE',
      headers: this.getPlatformHeaders(),
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
      research?: boolean
      conversationId?: string
      requirePlanApproval?: boolean
      permissionMode?: 'ask' | 'allow' | 'deny'
      useToolSearch?: boolean
      maxSteps?: number | null
      allowedTools?: string[]
      contextCompactionThreshold?: number
      contextCompactionKeepRecent?: number
      onApproval?: (request: { callId: string; name: string; arguments: unknown }) => Promise<boolean>
      onPlanApproval?: (request: { planId: string; objective: string; steps: Array<{ step_id: string; tool: string; description: string }> }) => Promise<boolean>
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
        research: !!options.research,
        conversation_id: options.conversationId,
        permission_mode: options.permissionMode ?? 'ask',
        require_plan_approval: !!options.requirePlanApproval,
        use_tool_search: options.useToolSearch,
        max_steps: options.maxSteps ?? undefined,
        allowed_tools: options.allowedTools,
        context_compaction_threshold: options.contextCompactionThreshold,
        context_compaction_keep_recent: options.contextCompactionKeepRecent,
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
          const event = JSON.parse(trimmed.slice(6)) as { type: string; content: unknown }
          if (event.type === 'approval_required') {
            const content = event.content as { call_id?: string; name?: string; arguments?: unknown }
            const callId = content.call_id ?? ''
            const approved = callId && options.onApproval
              ? await options.onApproval({ callId, name: content.name ?? 'tool', arguments: content.arguments })
              : false
            if (callId) await this.approveAgentCall(callId, !!approved)
          }
          if (event.type === 'plan_approval_required') {
            const content = event.content as { plan_id?: string; objective?: string; steps?: Array<{ step_id: string; tool: string; description: string }> }
            const planId = content.plan_id ?? ''
            const approved = planId && options.onPlanApproval
              ? await options.onPlanApproval({ planId, objective: content.objective ?? '', steps: content.steps ?? [] })
              : false
            if (planId) await this.approveAgentCall(planId, !!approved)
          }
          options.onEvent(event)
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
    let completed = false
    let fullReasoning = ''

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
          if (data === '[DONE]') {
            completed = true
            continue
          }

          let parsed: {
            error?: { message?: string }
            choices?: Array<{ delta?: { content?: string; reasoning_content?: string }; finish_reason?: 'stop' | 'length' | null }>
            usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
          }
          try {
            parsed = JSON.parse(data)
          } catch {
            // skip malformed JSON chunks
            continue
          }
          if (parsed.error) {
            throw new Error(parsed.error.message ?? 'The model provider could not complete this request.')
          }
          const delta = parsed.choices?.[0]?.delta?.content ?? ''
          const reasoning = parsed.choices?.[0]?.delta?.reasoning_content ?? ''
          fullReasoning += reasoning
          const finishReason = parsed.choices?.[0]?.finish_reason ?? null

          // Some servers emit a trailing usage object on the final SSE event.
          if (parsed.usage) {
            usage = {
              promptTokens: parsed.usage.prompt_tokens ?? 0,
              completionTokens: parsed.usage.completion_tokens ?? 0,
              totalTokens: parsed.usage.total_tokens ?? 0,
            }
          }

          fullContent += delta
          if (delta || reasoning || finishReason) {
            onChunk({ content: fullContent, reasoning: fullReasoning, finishReason, usage })
          }
        }
      }
      if (!completed) throw new Error('The reply was interrupted. Retry when you reconnect.')
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        onChunk({ content: fullContent, reasoning: fullReasoning, finishReason: 'stop' })
      }
      throw error
    } finally {
      await reader.cancel().catch(() => undefined)
      reader.releaseLock()
    }

    return fullContent
  }
}

export interface PlatformUser {
  id: string
  name: string
  email: string
  role: string
  createdAt: number
  updatedAt: number
}

export const apiClient = new ApiClient()
