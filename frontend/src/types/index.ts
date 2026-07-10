export interface TokenUsage {
  promptTokens: number
  completionTokens: number
  totalTokens: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  error?: boolean
  model?: string
  usage?: TokenUsage
  /** Data-URL images attached to a user message (for display + vision send). */
  images?: string[]
  /** How attached images were handled: sent to a vision model, or OCR'd to text. */
  imageMode?: 'vision' | 'ocr'
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
}

export interface StreamChunk {
  content: string
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
  dataUrl?: string
  preview?: string
}

export type Theme = 'light' | 'dark'
