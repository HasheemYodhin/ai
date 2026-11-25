/**
 * PDF export. jsPDF only places text, so this lays the parsed reply out the way
 * a document should look: a title, heading levels that stay with the text that
 * follows them, wrapped paragraphs with bold/italic/links, nested lists, tables
 * with a repeating header row, shaded code blocks, and "Page X of Y".
 *
 * PDFs use the built-in Helvetica/Courier fonts, which cover Latin text only.
 * Other scripts cannot be drawn with them; a note at the end of the file says
 * so and points to the Word export.
 */
import { inlinesToText, parseDocument, type Align, type Block, type Inline } from './parse'

type JsPdfClass = typeof import('jspdf').jsPDF
type Pdf = InstanceType<JsPdfClass>
type FontStyle = 'normal' | 'bold' | 'italic' | 'bolditalic'

const PAGE_WIDTH = 595.28
const PAGE_HEIGHT = 841.89
const MARGIN = { left: 56, right: 56, top: 62, bottom: 66 }
const CONTENT_WIDTH = PAGE_WIDTH - MARGIN.left - MARGIN.right
const BOTTOM_LIMIT = PAGE_HEIGHT - MARGIN.bottom

const COLORS = {
  ink: '#1F2937',
  muted: '#4B5563',
  faint: '#6B7280',
  heading: '#1F3A5F',
  accent: '#C2410C',
  rule: '#D1D5DB',
  codeBackground: '#F3F4F6',
  tableHeader: '#E8EEF7',
  link: '#0563C1',
}

// ── Text that the built-in fonts can draw ──────────────────────────────────

const REPLACEMENTS: Record<string, string> = {
  '\u2192': '->', '\u2190': '<-', '\u2194': '<->', '\u21D2': '=>',
  '\u2713': '[x]', '\u2714': '[x]', '\u2611': '[x]', '\u2717': '[ ]', '\u2718': '[ ]', '\u2610': '[ ]',
  '\u2265': '>=', '\u2264': '<=', '\u2260': '!=', '\u2248': '~', '\u2212': '-',
  '\u2010': '-', '\u2011': '-', '\u2012': '-', '\u2032': "'", '\u2033': '"',
  '\u00A0': ' ', '\u2002': ' ', '\u2003': ' ', '\u2009': ' ', '\u202F': ' ', '\u00AD': '',
}
// The characters Windows-1252 adds above Latin-1, which PDF's standard fonts include.
const WIN_ANSI_EXTRA = new Set('\u20AC\u201A\u0192\u201E\u2026\u2020\u2021\u02C6\u2030\u0160\u2039\u0152\u017D\u2018\u2019\u201C\u201D\u2022\u2013\u2014\u02DC\u2122\u0161\u203A\u0153\u017E\u0178')
const INVISIBLE = /\p{Extended_Pictographic}|\p{M}|[\u200B-\u200D\u2060]/u

/** Maps text onto what the standard PDF fonts can show. `lostLetters` counts letters that could not be. */
export function toPdfText(input: string): { text: string; lostLetters: number } {
  let text = ''
  let lostLetters = 0
  for (const char of input.normalize('NFC')) {
    const code = char.codePointAt(0) ?? 0
    if (code === 0x09) { text += '    '; continue }
    if (code < 0x20 || code === 0x7f) continue
    if (char in REPLACEMENTS) { text += REPLACEMENTS[char]; continue }
    if (code <= 0xff || WIN_ANSI_EXTRA.has(char)) { text += char; continue }
    if (INVISIBLE.test(char)) continue
    if (/[\p{L}\p{N}]/u.test(char)) lostLetters += 1
    text += '?'
  }
  return { text, lostLetters }
}

// ── Layout model ───────────────────────────────────────────────────────────

interface Word {
  text: string
  style: FontStyle
  code: boolean
  link?: string
  strike?: boolean
  width: number
  /** Gap before the word; 0 at the start of a line. */
  gap: number
}
interface Line { words: Word[]; width: number }
interface TextStyle { bold?: boolean; italic?: boolean }

const HEADINGS = {
  1: { size: 18, before: 24, after: 8 },
  2: { size: 14.5, before: 18, after: 6 },
  3: { size: 12.5, before: 14, after: 4 },
  4: { size: 11.5, before: 12, after: 3 },
} as const

const BODY_SIZE = 11
const LINE_RATIO = 1.45

const letter = (index: number) => String.fromCharCode(97 + (index % 26))

class PdfWriter {
  private y = MARGIN.top
  private lostLetters = 0
  private quoteDepth = 0
  private readonly widths = new Map<string, number>()

  constructor(private readonly doc: Pdf) {}

  // ── measuring and drawing text ──

  private font(style: FontStyle, size: number, code = false) {
    this.doc.setFont(code ? 'courier' : 'helvetica', style)
    this.doc.setFontSize(size)
  }

  private measure(text: string, style: FontStyle, size: number, code = false): number {
    const key = `${code ? 'c' : 'h'}|${style}|${size}|${text}`
    let width = this.widths.get(key)
    if (width === undefined) {
      this.font(style, size, code)
      width = this.doc.getTextWidth(text)
      this.widths.set(key, width)
    }
    return width
  }

  private styleFor(item: Inline, base: TextStyle): FontStyle {
    const bold = item.bold || base.bold
    const italic = item.italic || base.italic
    return bold && italic ? 'bolditalic' : bold ? 'bold' : italic ? 'italic' : 'normal'
  }

  /** Breaks inline runs into lines no wider than `width`. */
  private layout(inlines: Inline[], width: number, size: number, base: TextStyle = {}): Line[] {
    const lines: Line[] = []
    let line: Line = { words: [], width: 0 }
    const endLine = () => { lines.push(line); line = { words: [], width: 0 } }
    let pendingSpace = false

    for (const item of inlines) {
      if (item.br) { endLine(); pendingSpace = false; continue }
      const { text, lostLetters } = toPdfText(item.text)
      this.lostLetters += lostLetters
      const style = this.styleFor(item, base)
      const code = !!item.code
      const fontSize = code ? size * 0.92 : size

      for (const token of text.match(/\s+|\S+/g) ?? []) {
        if (/^\s/.test(token)) { pendingSpace = true; continue }
        let remaining = token
        while (remaining) {
          let chunk = remaining
          let chunkWidth = this.measure(chunk, style, fontSize, code)
          // A single word wider than the line (a long URL) is split by characters.
          if (chunkWidth > width) {
            let cut = chunk.length
            while (cut > 1 && this.measure(chunk.slice(0, cut), style, fontSize, code) > width) cut -= 1
            chunk = chunk.slice(0, cut)
            chunkWidth = this.measure(chunk, style, fontSize, code)
          }
          let gap = pendingSpace && line.words.length ? this.measure(' ', style, fontSize, code) : 0
          if (line.words.length && line.width + gap + chunkWidth > width) { endLine(); gap = 0 }
          line.words.push({ text: chunk, style, code, link: item.link, strike: item.strike, width: chunkWidth, gap })
          line.width += gap + chunkWidth
          pendingSpace = false
          remaining = remaining.slice(chunk.length)
        }
      }
    }
    if (line.words.length) endLine()
    return lines
  }

  private drawLine(line: Line, x: number, top: number, lineHeight: number, size: number, width: number, color: string, align: Align = null) {
    const { doc } = this
    const baseline = top + lineHeight * 0.78
    let cursor = x
    if (align === 'right') cursor = x + width - line.width
    else if (align === 'center') cursor = x + (width - line.width) / 2

    for (const word of line.words) {
      cursor += word.gap
      const fontSize = word.code ? size * 0.92 : size
      if (word.code) {
        doc.setFillColor(COLORS.codeBackground)
        doc.rect(cursor - 1.5, baseline - fontSize * 0.88, word.width + 3, fontSize * 1.2, 'F')
      }
      this.font(word.style, fontSize, word.code)
      doc.setTextColor(word.link ? COLORS.link : color)
      doc.text(word.text, cursor, baseline)
      if (word.link) {
        doc.setDrawColor(COLORS.link)
        doc.setLineWidth(0.5)
        doc.line(cursor, baseline + 1.6, cursor + word.width, baseline + 1.6)
        doc.link(cursor, baseline - fontSize, word.width, fontSize + 3, { url: word.link })
      }
      if (word.strike) {
        doc.setDrawColor(color)
        doc.setLineWidth(0.6)
        doc.line(cursor, baseline - fontSize * 0.3, cursor + word.width, baseline - fontSize * 0.3)
      }
      cursor += word.width
    }
  }

  // ── pages ──

  private ensure(height: number) {
    if (this.y + height > BOTTOM_LIMIT) this.newPage()
  }

  private newPage() {
    this.doc.addPage()
    this.y = MARGIN.top
  }

  private get atPageTop() {
    return this.y <= MARGIN.top + 0.5
  }

  // ── blocks ──

  private paragraph(inlines: Inline[], x: number, width: number, size = BODY_SIZE, color = COLORS.ink, base: TextStyle = {}) {
    const lineHeight = size * LINE_RATIO
    const style = this.quoteDepth ? { ...base, italic: true } : base
    for (const line of this.layout(inlines, width, size, style)) {
      this.ensure(lineHeight)
      this.drawLine(line, x, this.y, lineHeight, size, width, this.quoteDepth ? COLORS.muted : color)
      this.y += lineHeight
    }
  }

  private title(text: string) {
    const lines = this.layout([{ text }], CONTENT_WIDTH, 26, { bold: true })
    for (const line of lines) {
      this.ensure(26 * 1.25)
      this.drawLine(line, MARGIN.left, this.y, 26 * 1.25, 26, CONTENT_WIDTH, COLORS.heading)
      this.y += 26 * 1.25
    }
    this.y += 4
    this.doc.setDrawColor(COLORS.accent)
    this.doc.setLineWidth(1.5)
    this.doc.line(MARGIN.left, this.y, MARGIN.left + CONTENT_WIDTH, this.y)
    this.y += 22
  }

  private heading(block: Extract<Block, { type: 'heading' }>, x: number, width: number) {
    const spec = HEADINGS[block.level]
    const lineHeight = spec.size * 1.3
    const lines = this.layout(block.inlines, width, spec.size, { bold: true })
    const before = this.atPageTop ? 0 : spec.before
    // Keep the heading with the text after it: it needs room for itself and two lines of body.
    this.ensure(before + lines.length * lineHeight + spec.after + BODY_SIZE * LINE_RATIO * 2)
    this.y += this.atPageTop ? 0 : before
    for (const line of lines) {
      this.drawLine(line, x, this.y, lineHeight, spec.size, width, COLORS.heading)
      this.y += lineHeight
    }
    if (block.level === 1) {
      this.doc.setDrawColor(COLORS.rule)
      this.doc.setLineWidth(0.7)
      this.doc.line(x, this.y + 2, x + width, this.y + 2)
      this.y += 4
    }
    this.y += spec.after
  }

  private list(block: Extract<Block, { type: 'list' }>, level: number, x: number, width: number) {
    const lineHeight = BODY_SIZE * LINE_RATIO
    const markerWidth = block.ordered ? 22 : 15
    const itemX = x + 4
    const textX = itemX + markerWidth

    block.items.forEach((item, index) => {
      const marker = item.checked !== null
        ? (item.checked ? '[x]' : '[ ]')
        : block.ordered
          ? `${level === 0 ? block.start + index : letter(index)}.`
          : ['\u2022', '\u2013', '\u00B7'][Math.min(level, 2)]
      const [first, ...rest] = item.blocks
      const textWidth = width - (textX - x)

      if (first?.type === 'paragraph') {
        const lines = this.layout(first.inlines, textWidth, BODY_SIZE)
        lines.forEach((line, lineIndex) => {
          this.ensure(lineHeight)
          if (lineIndex === 0) {
            this.font('normal', BODY_SIZE)
            this.doc.setTextColor(COLORS.muted)
            this.doc.text(marker, itemX, this.y + lineHeight * 0.78)
          }
          this.drawLine(line, textX, this.y, lineHeight, BODY_SIZE, textWidth, COLORS.ink)
          this.y += lineHeight
        })
      } else {
        this.ensure(lineHeight)
        this.font('normal', BODY_SIZE)
        this.doc.setTextColor(COLORS.muted)
        this.doc.text(marker, itemX, this.y + lineHeight * 0.78)
        this.y += lineHeight
        if (first) rest.unshift(first)
      }
      this.y += 3
      for (const inner of rest) {
        if (inner.type === 'list') this.list(inner, level + 1, textX - 4, width - (textX - 4 - x))
        else this.block(inner, textX, textWidth)
      }
    })
    this.y += 3
  }

  private table(block: Extract<Block, { type: 'table' }>, x: number, width: number) {
    const { doc } = this
    const size = 9.5
    const lineHeight = size * 1.4
    const pad = 6
    const columns = Math.max(block.header.length, ...block.rows.map(row => row.length), 1)

    const weights = Array.from({ length: columns }, (_, column) => {
      const lengths = [block.header[column], ...block.rows.map(row => row[column])].map(cell => (cell ? inlinesToText(cell).length : 0))
      return Math.min(40, Math.max(6, ...lengths))
    })
    const total = weights.reduce((sum, weight) => sum + weight, 0)
    const widths = weights.map(weight => Math.max(38, (width * weight) / total))
    const scale = width / widths.reduce((sum, value) => sum + value, 0)
    const columnWidths = widths.map(value => value * scale)

    const prepare = (cells: Inline[][], isHeader: boolean) => {
      const lines = columnWidths.map((columnWidth, column) =>
        this.layout(cells[column] ?? [], columnWidth - pad * 2, size, { bold: isHeader }))
      return { lines, height: Math.max(1, ...lines.map(cell => cell.length)) * lineHeight + pad * 2 }
    }

    const drawRow = (row: ReturnType<typeof prepare>, isHeader: boolean) => {
      let cursor = x
      if (isHeader) {
        doc.setFillColor(COLORS.tableHeader)
        doc.rect(x, this.y, width, row.height, 'F')
      }
      doc.setDrawColor(COLORS.rule)
      doc.setLineWidth(0.6)
      row.lines.forEach((cellLines, column) => {
        const columnWidth = columnWidths[column]
        doc.rect(cursor, this.y, columnWidth, row.height, 'S')
        cellLines.forEach((line, index) => {
          this.drawLine(line, cursor + pad, this.y + pad + index * lineHeight, lineHeight, size, columnWidth - pad * 2,
            isHeader ? COLORS.heading : COLORS.ink, block.align[column] ?? null)
        })
        cursor += columnWidth
      })
      this.y += row.height
    }

    const header = prepare(block.header, true)
    this.ensure(header.height + (block.rows[0] ? prepare(block.rows[0], false).height : 0))
    drawRow(header, true)
    for (const cells of block.rows) {
      const row = prepare(cells, false)
      if (this.y + row.height > BOTTOM_LIMIT) {
        this.newPage()
        drawRow(header, true) // repeat the header on the new page
      }
      drawRow(row, false)
    }
    this.y += 12
  }

  private code(block: Extract<Block, { type: 'code' }>, x: number, width: number) {
    const { doc } = this
    const size = 8.8
    const lineHeight = size * 1.45
    const pad = 9
    const charWidth = this.measure('M', 'normal', size, true)
    const maxChars = Math.max(10, Math.floor((width - pad * 2) / charWidth))

    const wrapped: string[] = []
    for (const source of block.text.split('\n')) {
      const { text, lostLetters } = toPdfText(source)
      this.lostLetters += lostLetters
      if (!text) { wrapped.push(''); continue }
      for (let start = 0; start < text.length; start += maxChars) wrapped.push(text.slice(start, start + maxChars))
    }

    this.y += 4
    wrapped.forEach((text, index) => {
      const isFirst = index === 0
      const isLast = index === wrapped.length - 1
      const rowHeight = lineHeight + (isFirst ? pad / 2 : 0) + (isLast ? pad / 2 : 0)
      this.ensure(rowHeight)
      doc.setFillColor(COLORS.codeBackground)
      doc.rect(x, this.y, width, rowHeight, 'F')
      doc.setFillColor(COLORS.accent)
      doc.rect(x, this.y, 2.5, rowHeight, 'F')
      this.font('normal', size, true)
      doc.setTextColor(COLORS.ink)
      doc.text(text, x + pad, this.y + (isFirst ? pad / 2 : 0) + lineHeight * 0.74)
      this.y += rowHeight
    })
    this.y += 10
  }

  private block(block: Block, x: number, width: number, keepWithNext = false) {
    switch (block.type) {
      case 'heading':
        this.heading(block, x, width)
        break
      case 'paragraph':
        // A line like "as follows:" must not be left alone at the bottom of a page.
        if (keepWithNext) {
          const height = this.layout(block.inlines, width, BODY_SIZE).length * BODY_SIZE * LINE_RATIO
          this.ensure(height + BODY_SIZE * LINE_RATIO * 3)
        }
        this.paragraph(block.inlines, x, width)
        this.y += 8
        break
      case 'list':
        this.list(block, 0, x, width)
        break
      case 'table':
        this.table(block, x, width)
        break
      case 'code':
        this.code(block, x, width)
        break
      case 'quote': {
        this.quoteDepth += 1
        for (const inner of block.blocks) {
          const page = this.doc.getCurrentPageInfo().pageNumber
          const startY = this.y
          this.block(inner, x + 16, width - 16)
          if (this.doc.getCurrentPageInfo().pageNumber === page) {
            this.doc.setFillColor(COLORS.rule)
            this.doc.rect(x + 3, startY, 2.5, Math.max(0, this.y - startY - 6), 'F')
          }
        }
        this.quoteDepth -= 1
        break
      }
      case 'rule':
        this.ensure(18)
        this.y += 6
        this.doc.setDrawColor(COLORS.rule)
        this.doc.setLineWidth(0.8)
        this.doc.line(x, this.y, x + width, this.y)
        this.y += 12
        break
    }
  }

  render(title: string | null, blocks: Block[]) {
    if (title) this.title(title)
    blocks.forEach((block, index) => {
      const introduces = block.type === 'paragraph' && index < blocks.length - 1 && inlinesToText(block.inlines).endsWith(':')
      this.block(block, MARGIN.left, CONTENT_WIDTH, introduces)
    })
    if (this.lostLetters > 0) {
      this.y += 6
      this.paragraph(
        [{ text: 'Some characters in this document (for example other writing systems) cannot be shown in a PDF. Download it as Word to keep them.', italic: true }],
        MARGIN.left, CONTENT_WIDTH, 9, COLORS.faint,
      )
    }
  }

  /** Draws the title (left) and "Page X of Y" (right) in the bottom margin of every page. */
  addFooters(label: string) {
    const { doc } = this
    const pages = doc.getNumberOfPages()
    const shortLabel = label ? (doc.splitTextToSize(toPdfText(label).text, 300) as string[])[0] : ''
    for (let page = 1; page <= pages; page += 1) {
      doc.setPage(page)
      this.font('normal', 8.5)
      doc.setTextColor(COLORS.faint)
      doc.setDrawColor(COLORS.rule)
      doc.setLineWidth(0.5)
      doc.line(MARGIN.left, PAGE_HEIGHT - 44, PAGE_WIDTH - MARGIN.right, PAGE_HEIGHT - 44)
      if (shortLabel) doc.text(shortLabel, MARGIN.left, PAGE_HEIGHT - 30)
      doc.text(`Page ${page} of ${pages}`, PAGE_WIDTH - MARGIN.right, PAGE_HEIGHT - 30, { align: 'right' })
    }
  }
}

/** Builds the PDF. Exported so tests and tools can inspect it without a browser. */
export function buildPdfDocument(JsPdf: JsPdfClass, content: string, fallbackTitle = '') {
  const parsed = parseDocument(content)
  const label = parsed.title ?? fallbackTitle
  const doc = new JsPdf({ unit: 'pt', format: 'a4', compress: true })
  doc.setProperties({ title: label || 'Document', creator: 'Dabba' })
  const writer = new PdfWriter(doc)
  writer.render(parsed.title, parsed.blocks)
  writer.addFooters(label)
  return doc
}

export async function createPdfBlob(content: string, fallbackTitle = ''): Promise<Blob> {
  const { jsPDF } = await import('jspdf')
  return buildPdfDocument(jsPDF, content, fallbackTitle).output('blob')
}
