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

export function downloadText(content: string, fmt: TextFormat, baseName: string) {
  // For code-ish formats, unwrap a dominant fenced block so the file is runnable.
  let body = CODE_EXTS.includes(fmt.ext) ? stripForCode(content, fmt.ext) : content

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
  const { jsPDF } = await import('jspdf')
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  const margin = 40
  const maxWidth = doc.internal.pageSize.getWidth() - margin * 2
  const pageHeight = doc.internal.pageSize.getHeight() - margin
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(11)
  const lines = doc.splitTextToSize(content, maxWidth) as string[]
  let y = margin
  for (const line of lines) {
    if (y > pageHeight) {
      doc.addPage()
      y = margin
    }
    doc.text(line, margin, y)
    y += 15
  }
  doc.save(safeFileName(baseName, 'pdf'))
}

export async function downloadDocx(content: string, baseName: string) {
  const { Document, Packer, Paragraph, TextRun } = await import('docx')
  const paragraphs = content.split('\n').map(
    line => new Paragraph({ children: [new TextRun(line)] })
  )
  const doc = new Document({ sections: [{ children: paragraphs }] })
  const blob = await Packer.toBlob(doc)
  triggerDownload(safeFileName(baseName, 'docx'), blob,
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
}

/**
 * Excel export. If the content contains a markdown table, that table becomes
 * the sheet rows; otherwise each line becomes a single-column row.
 */
export async function downloadXlsx(content: string, baseName: string) {
  const XLSX = await import('xlsx')
  const rows = parseMarkdownTable(content) ?? content.split('\n').map(l => [l])
  const ws = XLSX.utils.aoa_to_sheet(rows)
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Sheet1')
  const out = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })
  triggerDownload(safeFileName(baseName, 'xlsx'), new Blob([out]),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
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
