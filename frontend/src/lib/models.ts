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
  ollama: 'Ollama',
}

export function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider
}
