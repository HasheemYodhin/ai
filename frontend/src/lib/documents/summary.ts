import { cleanMarkdown, inlinesToText, parseDocument } from './parse'

const MAX_SUMMARY_LENGTH = 240

function shortenSummary(value: string): string {
  const text = value.replace(/\s+/g, ' ').trim()
  const short = text.split(/(?<=[.!?])\s+/).slice(0, 2).join(' ')
  if (short.length <= MAX_SUMMARY_LENGTH) return short
  const prefix = short.slice(0, MAX_SUMMARY_LENGTH - 1)
  const lastSpace = prefix.lastIndexOf(' ')
  return `${lastSpace > 0 ? prefix.slice(0, lastSpace) : prefix}…`
}

export function splitDocumentReply(reply: string): { body: string; summary: string } {
  const text = cleanMarkdown(reply)
  const marked = /^(?:Chat summary:|\*\*Chat summary:\*\*|\*\*Chat summary\*\*:)[ \t]*([^\n]*)(?:\n|$)/i.exec(text)
  const body = marked ? cleanMarkdown(text.slice(marked[0].length)) : text
  if (marked?.[1].trim()) return { body, summary: shortenSummary(marked[1]) }

  const { title, blocks } = parseDocument(body)
  const paragraph = blocks.find(block => block.type === 'paragraph')
  if (paragraph?.type === 'paragraph') return { body, summary: shortenSummary(inlinesToText(paragraph.inlines)) }

  const sections = blocks.flatMap(block => block.type === 'heading' ? [inlinesToText(block.inlines)] : []).slice(0, 3)
  if (sections.length) return { body, summary: shortenSummary(`Covers ${sections.join(', ')}.`) }

  const table = blocks.find(block => block.type === 'table')
  if (table?.type === 'table') {
    const columns = table.header.map(inlinesToText).filter(Boolean).slice(0, 4)
    const rows = table.rows.length
    return {
      body,
      summary: shortenSummary(`Includes ${rows} data ${rows === 1 ? 'row' : 'rows'}${columns.length ? ` with columns for ${columns.join(', ')}` : ''}.`),
    }
  }
  return { body, summary: title ? shortenSummary(`File prepared for ${title}.`) : 'Your requested file is ready to download.' }
}
