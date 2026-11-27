import type { DocumentTemplate } from './documents/templates'

/**
 * Export helpers for chat content.
 *
 * Text-based formats are pure client-side Blob downloads (no deps).
 * PDF / Word / Excel use libraries that are lazy-imported only when the
 * user actually picks that format, so they stay out of the main bundle.
 */

export interface TextFormat {
  ext: string
  label: string
  mime: string
}

export type DocumentFormat = 'pdf' | 'docx' | 'xlsx' | 'pptx' | 'md'

const DOCUMENT_MIME_TYPES: Record<DocumentFormat, string> = {
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  md: 'text/markdown',
}

// Broad set of text-based formats. Add more here as needed.
export const TEXT_FORMATS: TextFormat[] = [
  { ext: 'txt', label: 'Plain text', mime: 'text/plain' },
  { ext: 'md', label: 'Markdown', mime: 'text/markdown' },
  { ext: 'html', label: 'HTML', mime: 'text/html' },
  { ext: 'py', label: 'Python', mime: 'text/x-python' },
  { ext: 'js', label: 'JavaScript', mime: 'text/javascript' },
  { ext: 'ts', label: 'TypeScript', mime: 'text/typescript' },
  { ext: 'json', label: 'JSON', mime: 'application/json' },
  { ext: 'yaml', label: 'YAML', mime: 'text/yaml' },
  { ext: 'csv', label: 'CSV', mime: 'text/csv' },
  { ext: 'xml', label: 'XML', mime: 'application/xml' },
  { ext: 'css', label: 'CSS', mime: 'text/css' },
  { ext: 'sh', label: 'Shell', mime: 'text/x-shellscript' },
  { ext: 'sql', label: 'SQL', mime: 'application/sql' },
  { ext: 'java', label: 'Java', mime: 'text/x-java' },
  { ext: 'c', label: 'C', mime: 'text/x-csrc' },
  { ext: 'cpp', label: 'C++', mime: 'text/x-c++src' },
  { ext: 'go', label: 'Go', mime: 'text/x-go' },
  { ext: 'rs', label: 'Rust', mime: 'text/x-rustsrc' },
]

/** Slugify a chat title/first line into a safe base filename. */
export function safeFileName(base: string, ext: string): string {
  const slug = (base || 'dabba-export')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60) || 'dabba-export'
  return `${slug}.${ext}`
}

function triggerDownload(filename: string, data: Blob | string, mime = 'text/plain') {
  const blob = typeof data === 'string' ? new Blob([data], { type: mime }) : data
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error('Could not encode generated file'))
    reader.readAsDataURL(blob)
  })
}

/** Pull the first fenced code block out of a markdown string, if any. */
export function firstCodeBlock(content: string): { code: string; lang: string } | null {
  const match = /```(\w+)?\n([\s\S]*?)```/.exec(content)
  if (!match) return null
  return { lang: (match[1] ?? '').toLowerCase(), code: match[2].replace(/\n$/, '') }
}

/** Strip markdown code fences so an exported .py/.html file is runnable, not wrapped. */
function stripForCode(content: string, ext: string): string {
  const block = firstCodeBlock(content)
  // If the reply is essentially one code block, export just the code.
  if (block && block.code.length > content.length * 0.5) return block.code
  // For code-ish extensions with no single dominant block, keep raw content.
  void ext
  return content
}

const CODE_EXTS = ['py', 'js', 'ts', 'sh', 'html', 'css', 'sql', 'java', 'c', 'cpp', 'go', 'rs']

export async function downloadText(content: string, fmt: TextFormat, baseName: string) {
  // For code-ish formats, unwrap a dominant fenced block so the file is runnable.
  let body = CODE_EXTS.includes(fmt.ext) ? stripForCode(content, fmt.ext) : content
  // Markdown files drop the chat lead-in and closing line and end with one newline.
  if (fmt.ext === 'md') body = (await import('./documents/parse')).toMarkdownFile(content)

  // If exporting HTML and the content isn't already a full document, wrap it.
  if (fmt.ext === 'html' && !/^\s*<(!doctype|html)/i.test(body)) {
    body = `<!doctype html>\n<html>\n<head><meta charset="utf-8"><title>${escapeHtml(baseName)}</title></head>\n<body>\n<pre>${escapeHtml(body)}</pre>\n</body>\n</html>`
  }

  triggerDownload(safeFileName(baseName, fmt.ext), body, fmt.mime)
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export async function downloadPdf(content: string, baseName: string) {
  const blob = await createPdfBlob(content, baseName)
  triggerDownload(safeFileName(baseName, 'pdf'), blob, DOCUMENT_MIME_TYPES.pdf)
}

/** A laid out PDF: title, headings, lists, tables, code and page numbers (see documents/pdf.ts). */
export async function createPdfBlob(content: string, fallbackTitle = '', template?: DocumentTemplate): Promise<Blob> {
  return (await import('./documents/pdf')).createPdfBlob(content, fallbackTitle, template)
}

export async function downloadDocx(content: string, baseName: string) {
  const blob = await createDocxBlob(content, baseName)
  triggerDownload(safeFileName(baseName, 'docx'), blob, DOCUMENT_MIME_TYPES.docx)
}

/** A styled Word document: Title, Heading styles, real lists and tables, page numbers (see documents/docx.ts). */
export async function createDocxBlob(content: string, fallbackTitle = '', template?: DocumentTemplate): Promise<Blob> {
  return (await import('./documents/docx')).createDocxBlob(content, fallbackTitle, template)
}

/**
 * Excel export. If the content contains a markdown table, that table becomes
 * the sheet rows; otherwise each line becomes a single-column row.
 */
export async function downloadXlsx(content: string, baseName: string) {
  const blob = await createXlsxBlob(content)
  triggerDownload(safeFileName(baseName, 'xlsx'), blob, DOCUMENT_MIME_TYPES.xlsx)
}

export async function createXlsxBlob(content: string): Promise<Blob> {
  const { default: ExcelJS } = await import('exceljs')
  const rows = parseMarkdownTable(content) ?? content.split('\n').map(l => [l])
  const workbook = new ExcelJS.Workbook()
  workbook.creator = 'Dabba'
  const worksheet = workbook.addWorksheet('Sheet1')
  worksheet.addRows(rows)
  if (rows.length > 0) {
    worksheet.getRow(1).font = { bold: true }
    worksheet.columns.forEach(column => {
      const width = Math.min(
        60,
        Math.max(12, ...rows.map(row => String(row[(column.number ?? 1) - 1] ?? '').length + 2)),
      )
      column.width = width
    })
  }
  const out = await workbook.xlsx.writeBuffer()
  return new Blob([out], { type: DOCUMENT_MIME_TYPES.xlsx })
}

export async function downloadPptx(content: string, baseName: string) {
  const blob = await createPptxBlob(content, baseName)
  triggerDownload(safeFileName(baseName, 'pptx'), blob, DOCUMENT_MIME_TYPES.pptx)
}

export async function createPptxBlob(content: string, baseName: string): Promise<Blob> {
  const { default: PptxGenJS } = await import('pptxgenjs')
  const pptx = new PptxGenJS()
  pptx.layout = 'LAYOUT_WIDE'
  pptx.author = 'Dabba'
  pptx.subject = baseName
  pptx.title = baseName
  pptx.company = 'Dabba'
  pptx.theme = {
    headFontFace: 'Aptos Display',
    bodyFontFace: 'Aptos',
  }

  const sections = parsePresentationSections(content, baseName)
  sections.forEach((section, index) => {
    const slide = pptx.addSlide()
    slide.background = { color: index === 0 ? 'F4F7F2' : 'FFFFFF' }
    slide.addShape(pptx.ShapeType.rect, {
      x: 0,
      y: 0,
      w: 0.16,
      h: 7.5,
      fill: { color: '25A65A' },
      line: { color: '25A65A' },
    })
    slide.addText(section.title, {
      x: 0.65,
      y: index === 0 ? 1.6 : 0.55,
      w: 11.9,
      h: index === 0 ? 1.1 : 0.6,
      fontFace: 'Aptos Display',
      fontSize: index === 0 ? 30 : 24,
      bold: true,
      color: '18231C',
      margin: 0,
      breakLine: false,
    })
    if (index === 0) {
      slide.addText(section.body.join('\n') || 'Generated by Dabba', {
        x: 0.7,
        y: 3,
        w: 10.8,
        h: 2,
        fontFace: 'Aptos',
        fontSize: 17,
        color: '526159',
        margin: 0,
        breakLine: false,
        valign: 'top',
      })
    } else {
      slide.addText(
        section.body.slice(0, 8).map(text => ({
          text: stripMarkdown(text),
          options: { bullet: { indent: 16 }, hanging: 4, breakLine: true },
        })),
        {
          x: 0.8,
          y: 1.45,
          w: 11.4,
          h: 5.35,
          fontFace: 'Aptos',
          fontSize: 17,
          color: '334139',
          breakLine: false,
          margin: 0.06,
          paraSpaceAfter: 12,
          valign: 'top',
        }
      )
    }
    slide.addText(String(index + 1), {
      x: 12.15,
      y: 7.05,
      w: 0.5,
      h: 0.2,
      fontSize: 9,
      color: '7B887F',
      align: 'right',
      margin: 0,
    })
  })

  const result = await pptx.write({ outputType: 'blob', compression: true })
  if (result instanceof Blob) return result
  if (typeof result === 'string') return new Blob([result], { type: DOCUMENT_MIME_TYPES.pptx })
  if (result instanceof ArrayBuffer) return new Blob([result], { type: DOCUMENT_MIME_TYPES.pptx })
  return new Blob([new Uint8Array(result).buffer], { type: DOCUMENT_MIME_TYPES.pptx })
}

export async function createGeneratedDocument(
  content: string,
  baseName: string,
  format: DocumentFormat,
  template?: DocumentTemplate,
) {
  const creators: Record<DocumentFormat, () => Promise<Blob>> = {
    pdf: () => createPdfBlob(content, baseName, template),
    docx: () => createDocxBlob(content, baseName, template),
    md: async () => new Blob([(await import('./documents/parse')).toMarkdownFile(content)], { type: DOCUMENT_MIME_TYPES.md }),
    xlsx: () => createXlsxBlob(content),
    pptx: () => createPptxBlob(content, baseName),
  }
  const blob = await creators[format]()
  return {
    name: safeFileName(baseName, format),
    size: blob.size,
    type: DOCUMENT_MIME_TYPES[format],
    dataUrl: await blobToDataUrl(blob),
  }
}

/** Parse the first GitHub-flavored markdown table into a 2D array of cells. */
function parseMarkdownTable(content: string): string[][] | null {
  const lines = content.split('\n')
  const isSeparator = (l: string | undefined) => !!l && /^\s*\|?[\s:|-]+\|?\s*$/.test(l)

  // A table header is a "| ... |" row immediately followed by a separator row.
  let start = -1
  for (let i = 0; i < lines.length - 1; i++) {
    if (/\|.*\|/.test(lines[i]) && isSeparator(lines[i + 1])) {
      start = i
      break
    }
  }
  if (start === -1) return null

  const rows: string[][] = []
  for (let i = start; i < lines.length; i++) {
    const line = lines[i].trim()
    if (!line.includes('|')) break
    if (isSeparator(line)) continue // skip the header separator row
    const cells = line.replace(/^\||\|$/g, '').split('|').map(c => c.trim())
    rows.push(cells)
  }
  return rows.length ? rows : null
}

function stripMarkdown(value: string): string {
  return value
    .replace(/^\s*[-*+]\s+/, '')
    .replace(/^\s*\d+\.\s+/, '')
    .replace(/[`*_~]/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .trim()
}

function parsePresentationSections(content: string, fallbackTitle: string) {
  const lines = content.split('\n')
  const sections: { title: string; body: string[] }[] = []
  let current = { title: fallbackTitle || 'Dabba presentation', body: [] as string[] }

  for (const line of lines) {
    const heading = /^(#{1,3})\s+(.+)$/.exec(line.trim())
    if (heading) {
      if (current.body.length || sections.length === 0) sections.push(current)
      current = { title: stripMarkdown(heading[2]), body: [] }
      continue
    }
    const text = stripMarkdown(line)
    if (text) current.body.push(text)
  }
  if (current.body.length || !sections.length) sections.push(current)

  const slides: { title: string; body: string[] }[] = []
  for (const section of sections) {
    if (section.body.length <= 8) {
      slides.push(section)
      continue
    }
    for (let i = 0; i < section.body.length; i += 8) {
      slides.push({
        title: i === 0 ? section.title : `${section.title} (continued)`,
        body: section.body.slice(i, i + 8),
      })
    }
  }
  return slides.slice(0, 30)
}
