import type { ModelInfo, EffortTier } from '@/types'

/**
 * Static fallback list used only when the Dabba server's /v1/agent/models
 * endpoint is unreachable. The live catalog (43+ models across providers)
 * is loaded at runtime via useModels().
 */
export const FALLBACK_MODELS: ModelInfo[] = [
  { id: 'dabba-10m', name: 'dabba-10M', provider: 'dabba', tier: 'medium', description: 'Scratch-trained local transformer', has_key: true },
  { id: 'dabba-100m', name: 'dabba-100M', provider: 'dabba', tier: 'medium', description: 'High-capacity local', has_key: true },
  { id: 'dabba-1b', name: 'dabba-1B', provider: 'dabba', tier: 'high', description: 'Instruction finetuned preview', has_key: true },
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

/**
 * Whether a model can accept image input (vision). Based on well-known
 * vision-capable model families; the backend catalog doesn't expose a
 * per-model vision flag, so we match on id/provider patterns.
 */
export function isVisionModel(modelId: string, provider?: string): boolean {
  const id = modelId.toLowerCase()
  // OpenAI: gpt-4o / gpt-4-turbo / gpt-4.1 / gpt-5.x see images; o-series reasoning models do too.
  if (/^gpt-4o/.test(id) || /^gpt-4\.1/.test(id) || /^gpt-4-turbo/.test(id) || /^gpt-5/.test(id) || /^o[0-9]/.test(id)) return true
  // Anthropic Claude 3+ are all vision-capable.
  if (id.startsWith('claude')) return true
  // Google Gemini 1.5+/2.x are multimodal.
  if (id.startsWith('gemini')) return true
  // Some NVIDIA/HF vision models advertise it in the id.
  if (/vision|vl|llava|multimodal/.test(id)) return true
  void provider
  return false
}
