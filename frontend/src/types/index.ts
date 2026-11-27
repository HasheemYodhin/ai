export interface TokenUsage {
  promptTokens: number
  completionTokens: number
  totalTokens: number
}

export type ChatSource =
  | { kind: 'web'; title: string; url: string }
  | { kind: 'file'; title: string; messageId: string; pages?: number[] }

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  interrupted?: boolean
  recoveryRequestId?: string
  sources?: ChatSource[]
  reasoning?: string
  error?: boolean
  model?: string
  usage?: TokenUsage
  /** Data-URL images attached to a user message (for display + vision send). */
  images?: string[]
  /** How attached images were handled: sent to a vision model, or OCR'd to text. */
  imageMode?: 'vision' | 'ocr'
  /** Extracted PDF/Word/text content sent to the model but hidden from the chat bubble. */
  documentContext?: string
  /** Non-image files rendered as attachment cards in the user message. */
  documentAttachments?: DocumentAttachment[]
  /** Real binary documents generated from an assistant reply. */
  generatedFiles?: GeneratedFile[]
  /** Images the model generated in response to this message (data URLs). */
  generatedImages?: string[]
  /** True while this message represents an in-flight image generation request. */
  isGeneratingImage?: boolean
  /**
   * Real tool activity from a Dabba agent-loop turn (web search, MCP
   * connectors/plugins, research) — every mode that routes through
   * POST /v1/agent shares this same trace shape.
   */
  agentActivity?: AgentActivity
  /** True if this turn was sent via mic/voice-mode — triggers auto-spoken replies. */
  viaVoice?: boolean
}

export interface AgentStep {
  tool: string
  detail: string
  success?: boolean
}

export interface AgentActivity {
  /** Short label for what triggered this turn: "Web search", "GitHub", "Research", etc. */
  label: string
  steps: AgentStep[]
  done: boolean
}

export interface Project {
  id: string
  name: string
  description?: string
  /** System-prompt override automatically applied to every conversation in this project. */
  instructions?: string
  color: string
  createdAt: number
}

/** A reusable saved instruction — applied as a system-prompt override for one message. */
export interface Skill {
  id: string
  name: string
  description?: string
  instructions: string
  script?: string | null
  createdAt: number
}

export type CoworkStatus = 'inbox' | 'planned' | 'in_progress' | 'blocked' | 'done'
export type CoworkPriority = 'low' | 'medium' | 'high' | 'urgent'

export interface CoworkItem {
  id: string
  title: string
  description: string
  status: CoworkStatus
  priority: CoworkPriority
  assignee?: string | null
  dueAt?: number | null
  tags: string[]
  conversationId?: string | null
  createdAt: number
  updatedAt: number
}

export interface CoworkRun {
  id: string
  itemId: string
  taskId: string
  mode: 'safe' | 'agent'
  workspacePath?: string | null
  status: PlatformTask['status']
  output?: { content?: string; itemId?: string; runId?: string; toolCallCount?: number; changedFiles?: string[] } | null
  error?: string | null
  startedAt: number
  completedAt?: number | null
}

export interface DirectoryEntry {
  name: string
  path: string
}

export interface DirectoryListing {
  path: string | null
  parent: string | null
  roots: DirectoryEntry[]
  directories: DirectoryEntry[]
}

export type ScheduleCadence = 'interval' | 'daily' | 'weekly'

export interface ScheduledSkill {
  id: string
  name: string
  skillName: string
  instructions: string
  /** Model the schedule runs with; empty uses the server default. */
  model?: string | null
  cadence: ScheduleCadence
  intervalMinutes?: number | null
  timeOfDay?: string | null
  timeZone?: string
  weekdays: number[]
  enabled: boolean
  nextRunAt?: number | null
  lastRunAt?: number | null
  lastStatus?: string | null
  createdAt: number
  updatedAt: number
}

export interface ScheduledSkillRun {
  id: string
  scheduleId: string
  taskId?: string | null
  status: string
  triggeredBy: string
  output?: { content?: string; message?: string } | null
  error?: string | null
  startedAt: number
  completedAt?: number | null
}

export interface CoworkSubtask {
  id: string
  itemId: string
  title: string
  status: 'pending' | 'done'
  position: number
  createdAt: number
  updatedAt: number
}

export interface CoworkSchedule {
  id: string
  itemId: string
  cadence: 'interval' | 'daily' | 'weekly'
  intervalMinutes?: number | null
  timeOfDay?: string | null
  weekdays: number[]
  mode: 'safe' | 'agent'
  workspacePath?: string | null
  model?: string | null
  effort?: string | null
  enabled: boolean
  nextRunAt?: number | null
  lastRunAt?: number | null
  lastStatus?: string | null
  createdAt: number
  updatedAt: number
}

export interface AgentDefinition {
  id: string
  userId: string
  name: string
  description: string
  systemPrompt: string
  allowedTools: string[]
  model?: string | null
  effort?: string | null
  createdAt: number
  updatedAt: number
}

export type HookEvent = 'session_start' | 'session_end' | 'user_prompt_submit' | 'pre_tool_call' | 'post_tool_call'

export interface AgentHook {
  id: string
  event: HookEvent
  matcher: string
  command: string
  timeout: number
  enabled: boolean
  created_at: number
}

export interface HookRun {
  hook_id: string
  event: HookEvent
  tool: string
  exit_code: number | null
  blocked: boolean
  stdout: string
  stderr: string
  error: string
  duration_ms: number
  timestamp: number
}

export interface PlatformTask {
  id: string
  kind: string
  status: 'queued' | 'planning' | 'running' | 'waiting_for_approval' | 'retrying' | 'completed' | 'failed' | 'cancelled'
  request: Record<string, unknown>
  result?: Record<string, unknown> | null
  error?: { message?: string; type?: string; retryable?: boolean } | null
  progress: number
  currentStep?: string | null
  model?: string | null
  createdAt: number
  updatedAt: number
  completedAt?: number | null
}

export interface PlatformTaskEvent {
  id: number
  taskId: string
  type: string
  payload: Record<string, unknown>
  createdAt: number
}

export type EffortTier = 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export interface ModelInfo {
  id: string
  name: string
  provider: string
  tier: string
  description: string
  has_key: boolean
  keySource?: string | null
  contextWindow?: number
  maxOutputTokens?: number
  supportsThinking?: boolean
  supportsVision?: boolean
  fallbackModels?: string[]
}

export interface ModelCatalog {
  models: ModelInfo[]
  current: string
  effort: string
}

export interface McpServer {
  name: string
  command: string
  args: string[]
  connected: boolean
  processRunning?: boolean
  authenticated?: boolean
  authenticationStatus?: 'configured' | 'missing' | 'unverified'
  checkedAt?: number
  verifiedStatus?: 'connected' | 'degraded' | 'authentication_required' | 'stopped' | 'unknown'
  message?: string | null
  tools: string[]
}

export interface Conversation {
  id: string
  title: string
  messages: Message[]
  createdAt: number
  updatedAt: number
  tokenCount?: number
  pinned?: boolean
  customTitle?: boolean
  projectId?: string | null
  /** Number of messages on the server; set by the lightweight list. */
  revision?: number
  messageCount?: number
  /**
   * False for sidebar entries whose messages haven't been fetched yet
   * (`messages` is then []). Undefined/true means `messages` is complete.
   */
  messagesLoaded?: boolean
}

export interface StreamChunk {
  content: string
  reasoning?: string
  finishReason?: 'stop' | 'length' | null
  usage?: TokenUsage
}

export interface ChatCompletionRequest {
  model?: string
  messages: { role: string; content: unknown }[]
  stream?: boolean
  temperature?: number
  max_tokens?: number
  effort?: string
  top_p?: number
  presence_penalty?: number
  frequency_penalty?: number
  stop?: string[]
}

export interface ChatCompletionResponse {
  id: string
  object: string
  created: number
  model: string
  choices: {
    index: number
    message: { role: string; content: string }
    finish_reason: string | null
  }[]
}

export interface UploadedFile {
  id: string
  name: string
  size: number
  type: string
  /** Browser File retained for disk-backed multipart document uploads. */
  file?: File
  dataUrl?: string
  preview?: string
}

export interface ExtractedDocument {
  name: string
  text: string
  characters: number
  truncated: boolean
}

export interface DocumentAttachment {
  name: string
  size: number
  type: string
  dataUrl?: string
}

export interface GeneratedFile {
  name: string
  size: number
  type: string
  dataUrl: string
}

export type Theme = 'light' | 'dark'
