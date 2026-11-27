export const DOCUMENT_TEMPLATES = {
  professional: {
    label: 'Professional',
    outline: 'Use a short summary, clearly named sections, and recommendations or next steps if relevant.',
    heading: '1F3A5F', accent: 'C2410C', tableHeader: 'E8EEF7', titleSize: 26,
  },
  minimal: {
    label: 'Minimal',
    outline: 'Use a title and only the headings needed to organize the material. Go straight to the content and omit a separate summary unless requested.',
    heading: '27272A', accent: '71717A', tableHeader: 'F4F4F5', titleSize: 22,
  },
  technical: {
    label: 'Technical',
    outline: 'When relevant, organize as overview, requirements, implementation, and verification. Use numbered steps, tables for parameters, and fenced blocks for code.',
    heading: '134E4A', accent: '0F766E', tableHeader: 'E6F4F0', titleSize: 25,
  },
} as const

export type DocumentTemplate = keyof typeof DOCUMENT_TEMPLATES

export function normalizeDocumentTemplate(value: unknown): DocumentTemplate {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(DOCUMENT_TEMPLATES, value)
    ? value as DocumentTemplate
    : 'professional'
}

export function templateForPrompt(prompt: string, fallback: DocumentTemplate): DocumentTemplate {
  const match = /\b(?:use|using|with|in)\s+(?:the\s+|a\s+)?(professional|minimal|technical)\s+template\b|\btemplate\s*:\s*(professional|minimal|technical)\b/i.exec(prompt)
  return match ? normalizeDocumentTemplate((match[1] ?? match[2]).toLowerCase()) : fallback
}

export function documentTemplateInstruction(template: DocumentTemplate): string {
  return `Document template: ${DOCUMENT_TEMPLATES[template].label}. ${DOCUMENT_TEMPLATES[template].outline} Follow any specific structure requested by the user.`
}
