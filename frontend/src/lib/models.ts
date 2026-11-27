import type { ModelInfo, EffortTier } from '@/types'

/**
 * Static fallback list used only when the Dabba server's /v1/agent/models
 * endpoint is unreachable. The live catalog (43+ models across providers)
 * is loaded at runtime via useModels().
 */
export const FALLBACK_MODELS: ModelInfo[] = [
  { id: 'dabba', name: 'Dabba', provider: 'dabba', tier: 'medium', description: 'Scratch-trained local transformer', has_key: true },
]

export const EFFORT_TIERS: { id: EffortTier; label: string; hint: string }[] = [
  { id: 'low', label: 'Low', hint: 'Fastest, least reasoning' },
  { id: 'medium', label: 'Medium', hint: 'Balanced (default)' },
  { id: 'high', label: 'High', hint: 'More reasoning' },
  { id: 'xhigh', label: 'X-High', hint: 'Extended reasoning' },
  { id: 'max', label: 'Max', hint: 'Maximum reasoning depth' },
]

/** Human-friendly labels + accent classes for provider grouping in the picker. */
export const PROVIDER_LABELS: Record<string, string> = {
  dabba: 'Dabba (local)',
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  google: 'Google',
  nvidia: 'NVIDIA',
  huggingface: 'Hugging Face',
  vyceai: 'VyceAI',
  ollama: 'Ollama',
}

export function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider
}

// Last-known display names by model ID. The live catalog can briefly be empty
// (e.g. while /v1/agent/models reloads during a streaming reply); this cache
// keeps the picker and reply labels showing "Nemotron 3.5 Super VL 120B"
// instead of flashing the raw "nvidia/nemotron-..." ID.
const knownModelNames = new Map<string, string>()

export function rememberModelNames(models: Pick<ModelInfo, 'id' | 'name'>[]): void {
  for (const m of models) if (m.name) knownModelNames.set(m.id, m.name)
}

/** Display name for a model ID: catalog name if known, else the ID without its vendor prefix. */
export function modelDisplayName(id: string): string {
  return knownModelNames.get(id) ?? id.slice(id.lastIndexOf('/') + 1)
}

/** "200k context" / "1M context"; small windows in tokens; undefined when unknown (never "0k"). */
export function formatContextWindow(tokens?: number | null): string | undefined {
  if (!tokens || tokens <= 0) return undefined
  if (tokens >= 1_000_000) return `${+(tokens / 1_000_000).toFixed(tokens % 1_000_000 ? 2 : 0)}M context`
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}k context`
  return `${tokens} token context`
}
