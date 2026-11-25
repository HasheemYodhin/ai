/**
 * Turns a chat reply (Markdown) into a small document model that the PDF and
 * Word exporters lay out. Exporters never see raw Markdown symbols: headings,
 * lists, tables, code and inline bold/italic arrive as structure, so `##` and
 * `**` do not leak into the files.
 */
import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmFromMarkdown } from 'mdast-util-gfm'
import { gfm } from 'micromark-extension-gfm'
import type { PhrasingContent, RootContent } from 'mdast'

export interface Inline {
  text: string
  bold?: boolean
  italic?: boolean
  strike?: boolean
  code?: boolean
  link?: string
  /** A line break inside a paragraph; `text` is empty. */
  br?: boolean
}

export type Align = 'left' | 'center' | 'right' | null

export interface ListItem {
  /** Task list state: true/false for "[x]"/"[ ]", null for a normal item. */
  checked: boolean | null
  blocks: Block[]
}

export type Block =
  | { type: 'heading'; level: 1 | 2 | 3 | 4; inlines: Inline[] }
  | { type: 'paragraph'; inlines: Inline[] }
  | { type: 'list'; ordered: boolean; start: number; items: ListItem[] }
  | { type: 'table'; header: Inline[][]; rows: Inline[][][]; align: Align[] }
  | { type: 'code'; lang: string; text: string }
  | { type: 'quote'; blocks: Block[] }
  | { type: 'rule' }

export interface ParsedDocument {
  /** The document's `# Title`, when it starts with one. */
  title: string | null
  blocks: Block[]
}

// ── Cleaning ───────────────────────────────────────────────────────────────

const LEAD_IN = /^(sure|certainly|of course|absolutely|great|okay|ok|here(?:'s| is| are)|below is|i(?:'ve| have)\b|i(?:'ll| will)\b)/i
const CLOSING = /^(let me know|feel free|i hope|hope this|would you like|if you(?:'d| would)? like|happy to|do you want|is there anything|(?:good|best of) luck\b|enjoy\b|cheers\b|(?:thanks|thank you)[!.]?$)/i

const isRule = (line: string) => /^\s*([-*_])(\s*\1){2,}\s*$/.test(line)
const startsBlock = (line: string) => /^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|~~~)/.test(line)

/**
 * Tidies a reply before it becomes a file: unwraps a reply that is one big
 * ```markdown fence, drops a chatty lead-in ("Sure! Here is the report:") and
 * a closing offer ("Let me know if..."), and collapses stray blank lines.
 */
export function cleanMarkdown(raw: string): string {
  let text = raw.replace(/\r\n?/g, '\n').replace(/\u00A0/g, ' ').replace(/[ \t]+$/gm, '')

  const wrapped = /^\s*(`{3,}|~{3,})[ \t]*(?:markdown|md)[ \t]*\n([\s\S]*?)\n\1[ \t]*\s*$/i.exec(text)
  if (wrapped) text = wrapped[2]

  let lines = text.split('\n')
  const firstIndex = lines.findIndex(line => line.trim() !== '')
  if (firstIndex >= 0) {
    const first = lines[firstIndex].trim()
    const hasDocumentAfter = lines.slice(firstIndex + 1).some(line => /^\s*#{1,6}\s/.test(line))
    if (!startsBlock(first) && first.length <= 240 && LEAD_IN.test(first) && hasDocumentAfter) {
      lines = lines.slice(firstIndex + 1)
    }
  }

  let lastIndex = lines.length - 1
  while (lastIndex >= 0 && lines[lastIndex].trim() === '') lastIndex -= 1
  if (lastIndex >= 0) {
    const last = lines[lastIndex].trim()
    if (!startsBlock(last) && last.length <= 240 && CLOSING.test(last)) lines = lines.slice(0, lastIndex)
  }

  // Separator rules left over from the lead-in or closing.
  while (lines.length && (lines[0].trim() === '' || isRule(lines[0]))) lines.shift()
  while (lines.length && (lines[lines.length - 1].trim() === '' || isRule(lines[lines.length - 1]))) lines.pop()

  return lines.join('\n').replace(/\n{3,}/g, '\n\n')
}

// ── Parsing ────────────────────────────────────────────────────────────────

type Style = Pick<Inline, 'bold' | 'italic' | 'strike' | 'link'>

function inlinesOf(nodes: PhrasingContent[], style: Style = {}): Inline[] {
  const out: Inline[] = []
  for (const node of nodes) {
    switch (node.type) {
      case 'text':
        // A soft line break inside a paragraph is just a space.
        if (node.value) out.push({ text: node.value.replace(/\s*\n\s*/g, ' '), ...style })
        break
      case 'strong':
        out.push(...inlinesOf(node.children, { ...style, bold: true }))
        break
      case 'emphasis':
        out.push(...inlinesOf(node.children, { ...style, italic: true }))
        break
      case 'delete':
        out.push(...inlinesOf(node.children, { ...style, strike: true }))
        break
      case 'link':
        out.push(...inlinesOf(node.children, { ...style, link: node.url }))
        break
      case 'inlineCode':
        out.push({ text: node.value, code: true, ...style })
        break
      case 'break':
        out.push({ text: '', br: true })
        break
      case 'image':
        if (node.alt) out.push({ text: node.alt, ...style })
        break
      case 'html':
        if (/^<br\s*\/?>$/i.test(node.value.trim())) out.push({ text: '', br: true })
        break
      default:
        break
    }
  }
  return mergeInlines(out)
}

/** Joins neighbouring runs that share a style, so layouts see fewer pieces. */
function mergeInlines(inlines: Inline[]): Inline[] {
  const merged: Inline[] = []
  for (const item of inlines) {
    const previous = merged[merged.length - 1]
    const same = previous && !previous.br && !item.br &&
      previous.bold === item.bold && previous.italic === item.italic && previous.strike === item.strike &&
      previous.code === item.code && previous.link === item.link
    if (same) previous.text += item.text
    else merged.push({ ...item })
  }
  return merged
}

function blocksOf(nodes: RootContent[]): Block[] {
  const out: Block[] = []
  for (const node of nodes) {
    switch (node.type) {
      case 'heading':
        out.push({ type: 'heading', level: Math.min(node.depth, 4) as 1 | 2 | 3 | 4, inlines: inlinesOf(node.children) })
        break
      case 'paragraph': {
        const inlines = inlinesOf(node.children)
        if (inlines.length) out.push({ type: 'paragraph', inlines })
        break
      }
      case 'list':
        out.push({
          type: 'list',
          ordered: !!node.ordered,
          start: node.start ?? 1,
          items: node.children.map(item => ({
            checked: item.checked ?? null,
            blocks: blocksOf(item.children),
          })),
        })
        break
      case 'table': {
        const [head, ...body] = node.children
        out.push({
          type: 'table',
          header: head.children.map(cell => inlinesOf(cell.children)),
          rows: body.map(row => row.children.map(cell => inlinesOf(cell.children))),
          align: (node.align ?? []).map(value => value ?? null),
        })
        break
      }
      case 'code':
        out.push({ type: 'code', lang: node.lang ?? '', text: node.value })
        break
      case 'blockquote':
        out.push({ type: 'quote', blocks: blocksOf(node.children) })
        break
      case 'thematicBreak':
        out.push({ type: 'rule' })
        break
      default:
        break // raw HTML, link definitions and footnotes are not exported
    }
  }
  return out
}

export function inlinesToText(inlines: Inline[]): string {
  return inlines.map(item => (item.br ? ' ' : item.text)).join('').replace(/\s+/g, ' ').trim()
}

/**
 * Parses a reply into a title and blocks. A leading `# Title` becomes the
 * document title; headings are then renumbered so the highest level used in the
 * body is level 1 (models usually write `##` sections under a `#` title).
 */
export function parseDocument(markdown: string): ParsedDocument {
  const tree = fromMarkdown(cleanMarkdown(markdown), {
    extensions: [gfm()],
    mdastExtensions: [gfmFromMarkdown()],
  })
  const blocks = blocksOf(tree.children)

  let title: string | null = null
  const first = blocks[0]
  if (first?.type === 'heading' && first.level === 1) {
    title = inlinesToText(first.inlines) || null
    blocks.shift()
  }

  const levels: number[] = []
  const collect = (list: Block[]) => {
    for (const block of list) {
      if (block.type === 'heading') levels.push(block.level)
      else if (block.type === 'quote') collect(block.blocks)
    }
  }
  collect(blocks)
  const shift = levels.length ? Math.min(...levels) - 1 : 0
  if (shift > 0) {
    const renumber = (list: Block[]) => {
      for (const block of list) {
        if (block.type === 'heading') block.level = Math.max(1, block.level - shift) as 1 | 2 | 3 | 4
        else if (block.type === 'quote') renumber(block.blocks)
      }
    }
    renumber(blocks)
  }
  return { title, blocks }
}

/** The Markdown to save as a `.md` file: the cleaned reply, ending with one newline. */
export function toMarkdownFile(raw: string): string {
  const cleaned = cleanMarkdown(raw)
  return cleaned ? `${cleaned}\n` : ''
}
