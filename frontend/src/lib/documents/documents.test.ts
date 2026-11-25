// @vitest-environment node
import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'
import * as docx from 'docx'
import { jsPDF } from 'jspdf'
import { buildDocxDocument } from './docx'
import { buildPdfDocument, toPdfText } from './pdf'
import { cleanMarkdown, parseDocument, toMarkdownFile } from './parse'

const SAMPLE = [
  "Sure! Here is the report you asked for:",
  '',
  '# Quarterly report',
  '',
  'This covers **uptime** and [the status page](https://example.com/status).',
  '',
  '## Results',
  '',
  '- First point',
  '  - Nested point',
  '- Second point',
  '',
  '1. Step one',
  '2. Step two',
  '',
  '| Service | Uptime |',
  '| :--- | ---: |',
  '| API | 99.9% |',
  '| Web | 99.5% |',
  '',
  '### Script',
  '',
  '```python',
  'print("hello")',
  '```',
  '',
  '---',
  '',
  'Let me know if you would like changes!',
].join('\n')

describe('cleaning a reply before it becomes a file', () => {
  it('drops the chat lead-in, the closing offer and the divider', () => {
    const cleaned = cleanMarkdown(SAMPLE)
    expect(cleaned.startsWith('# Quarterly report')).toBe(true)
    expect(cleaned).not.toContain('Sure!')
    expect(cleaned).not.toContain('Let me know')
    expect(cleaned.trimEnd().endsWith('```')).toBe(true)
  })

  it('unwraps a reply that is one big markdown code fence, but leaves real code alone', () => {
    expect(cleanMarkdown('```markdown\n# Title\n\nBody\n```')).toBe('# Title\n\nBody')
    expect(cleanMarkdown('```python\nprint(1)\n```')).toBe('```python\nprint(1)\n```')
  })

  it('keeps a first line that is real content', () => {
    expect(cleanMarkdown('Here are the facts.\n\nNo headings follow.')).toContain('Here are the facts.')
  })

  it('saves a markdown file that ends with exactly one newline', () => {
    const file = toMarkdownFile(SAMPLE)
    expect(file.endsWith('```\n')).toBe(true)
    expect(file.endsWith('\n\n')).toBe(false)
    expect(toMarkdownFile('   ')).toBe('')
  })
})

describe('parsing a reply into a document', () => {
  it('takes the # line as the title and promotes the headings under it', () => {
    const parsed = parseDocument(SAMPLE)
    expect(parsed.title).toBe('Quarterly report')
    const headings = parsed.blocks.filter(block => block.type === 'heading')
    expect(headings.map(block => block.type === 'heading' && block.level)).toEqual([1, 2])
  })

  it('finds lists, a table with alignment, and code', () => {
    const { blocks } = parseDocument(SAMPLE)
    const table = blocks.find(block => block.type === 'table')
    expect(table?.type === 'table' && table.align).toEqual(['left', 'right'])
    expect(table?.type === 'table' && table.rows).toHaveLength(2)
    const lists = blocks.filter(block => block.type === 'list')
    expect(lists.map(block => block.type === 'list' && block.ordered)).toEqual([false, true])
    expect(blocks.some(block => block.type === 'code' && block.lang === 'python')).toBe(true)
  })

  it('renders bold and links as styles, not as symbols', () => {
    const paragraph = parseDocument('# T\n\nA **bold** [link](https://example.com).').blocks[0]
    expect(paragraph.type === 'paragraph' && paragraph.inlines.some(item => item.bold && item.text === 'bold')).toBe(true)
    expect(paragraph.type === 'paragraph' && paragraph.inlines.some(item => item.link === 'https://example.com')).toBe(true)
  })

  it('does not invent a title when the reply has no # line', () => {
    expect(parseDocument('## Only a section\n\nText').title).toBeNull()
  })
})

describe('Word export', () => {
  async function wordFiles() {
    const buffer = await docx.Packer.toBuffer(buildDocxDocument(docx, parseDocument(SAMPLE), 'Chat title'))
    const zip = await JSZip.loadAsync(buffer)
    const body = await zip.file('word/document.xml')!.async('string')
    const footer = await zip.file('word/footer1.xml')!.async('string')
    return { body, footer }
  }

  it('uses real Title and Heading styles, a table, lists and a hyperlink', async () => {
    const { body } = await wordFiles()
    expect(body).toContain('w:val="Title"')
    expect(body).toContain('w:val="Heading1"')
    expect(body).toContain('w:val="Heading2"')
    expect(body).toContain('<w:tbl>')
    expect(body).toContain('<w:tblHeader/>')
    expect(body).toContain('<w:numPr>')
    expect(body).toContain('<w:hyperlink')
  })

  it('has no Markdown symbols in the visible text', async () => {
    const { body } = await wordFiles()
    const text = body.replace(/<[^>]+>/g, '')
    for (const symbol of ['**', '## ', '```', '| ---']) expect(text).not.toContain(symbol)
    expect(text).not.toContain('Sure!')
  })

  it('puts page numbers in the footer', async () => {
    expect((await wordFiles()).footer).toContain('PAGE')
  })
})

describe('PDF export', () => {
  it('makes a PDF and starts a new page when the content is long', () => {
    const short = buildPdfDocument(jsPDF, SAMPLE, 'Chat title')
    expect(short.output('arraybuffer').byteLength).toBeGreaterThan(1000)
    expect(short.getNumberOfPages()).toBe(1)
    const long = buildPdfDocument(jsPDF, `# Long\n\n${Array.from({ length: 120 }, (_, i) => `Paragraph ${i} with some text.`).join('\n\n')}`)
    expect(long.getNumberOfPages()).toBeGreaterThan(1)
  })

  it('maps symbols the PDF fonts cannot draw and counts letters it must drop', () => {
    const arrow = String.fromCodePoint(0x2192)
    const rocket = String.fromCodePoint(0x1f680)
    const tamil = String.fromCodePoint(0x0bb5)
    expect(toPdfText(`a ${arrow} b ${rocket}`).text).toBe('a -> b ')
    expect(toPdfText('Café – “quoted”').text).toBe('Café – “quoted”')
    expect(toPdfText(`x${tamil}`)).toEqual({ text: 'x?', lostLetters: 1 })
  })
})
