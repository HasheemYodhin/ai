/**
 * Word (.docx) export. Builds a real document from the parsed reply: a Title,
 * Heading 1-4 styles (so Word's navigation pane and table of contents work),
 * true bullet and numbered lists, shaded tables with a repeating header row,
 * code blocks, and "Page X of Y" in the footer.
 */
import { inlinesToText, parseDocument, type Block, type Inline, type ParsedDocument } from './parse'

type Docx = typeof import('docx')
type Child = import('docx').Paragraph | import('docx').Table

// Layout, in twentieths of a point (A4 with 2.3 cm side margins).
const PAGE_MARGIN = 1304
const CONTENT_WIDTH = 11906 - PAGE_MARGIN * 2

const COLORS = {
  ink: '1F2937',
  muted: '4B5563',
  heading: '1F3A5F',
  accent: 'C2410C',
  border: 'D1D5DB',
  codeBackground: 'F3F4F6',
  tableHeader: 'E8EEF7',
  link: '0563C1',
}

const BODY_FONT = 'Calibri'
const CODE_FONT = 'Consolas'

interface RunBase {
  bold?: boolean
  italics?: boolean
  color?: string
}

function runs(docx: Docx, inlines: Inline[], base: RunBase = {}) {
  const { TextRun, ExternalHyperlink } = docx
  return inlines.map(item => {
    if (item.br) return new TextRun({ break: 1 })
    const common = {
      text: item.text,
      bold: base.bold || item.bold || undefined,
      italics: base.italics || item.italic || undefined,
      strike: item.strike || undefined,
      color: base.color,
    }
    if (item.link) {
      return new ExternalHyperlink({
        link: item.link,
        children: [new TextRun({ ...common, style: 'Hyperlink' })],
      })
    }
    if (item.code) {
      return new TextRun({
        ...common,
        font: CODE_FONT,
        size: 20,
        shading: { type: docx.ShadingType.CLEAR, fill: COLORS.codeBackground, color: 'auto' },
      })
    }
    return new TextRun(common)
  })
}

/** Column widths that follow how much text each column holds. */
function columnWidths(header: Inline[][], rows: Inline[][][]): number[] {
  const count = Math.max(header.length, ...rows.map(row => row.length), 1)
  const weights = Array.from({ length: count }, (_, column) => {
    const lengths = [header[column], ...rows.map(row => row[column])].map(cell => (cell ? inlinesToText(cell).length : 0))
    return Math.min(40, Math.max(6, ...lengths))
  })
  const total = weights.reduce((sum, weight) => sum + weight, 0)
  const widths = weights.map(weight => Math.floor((CONTENT_WIDTH * weight) / total))
  widths[widths.length - 1] += CONTENT_WIDTH - widths.reduce((sum, width) => sum + width, 0)
  return widths
}

interface Context {
  /** Each ordered list gets its own numbering instance so every list starts at 1. */
  orderedInstance: number
}

function renderBlock(docx: Docx, block: Block, context: Context, indent = 0): Child[] {
  const { Paragraph, Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType, AlignmentType, HeadingLevel, TextRun } = docx
  const headings = [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3, HeadingLevel.HEADING_4]

  switch (block.type) {
    case 'heading':
      return [new Paragraph({ heading: headings[block.level - 1], children: runs(docx, block.inlines) })]

    case 'paragraph':
      return [new Paragraph({
        indent: indent ? { left: indent } : undefined,
        // A line ending in a colon stays on the same page as what it introduces.
        keepNext: inlinesToText(block.inlines).endsWith(':') || undefined,
        children: runs(docx, block.inlines),
      })]

    case 'list':
      return renderList(docx, block, context, 0)

    case 'table': {
      const widths = columnWidths(block.header, block.rows)
      const line = { style: BorderStyle.SINGLE, size: 4, color: COLORS.border }
      const align = (column: number) => {
        const value = block.align[column]
        return value === 'center' ? AlignmentType.CENTER : value === 'right' ? AlignmentType.RIGHT : AlignmentType.LEFT
      }
      const makeRow = (cells: Inline[][], isHeader: boolean) =>
        new TableRow({
          tableHeader: isHeader || undefined,
          cantSplit: true,
          children: widths.map((width, column) =>
            new TableCell({
              width: { size: width, type: WidthType.DXA },
              shading: isHeader ? { type: ShadingType.CLEAR, fill: COLORS.tableHeader, color: 'auto' } : undefined,
              margins: { top: 70, bottom: 70, left: 110, right: 110 },
              children: [
                new Paragraph({
                  alignment: align(column),
                  spacing: { after: 0 },
                  children: runs(docx, cells[column] ?? [], { bold: isHeader }),
                }),
              ],
            })),
        })
      return [
        new Table({
          width: { size: CONTENT_WIDTH, type: WidthType.DXA },
          columnWidths: widths,
          borders: { top: line, bottom: line, left: line, right: line, insideHorizontal: line, insideVertical: line },
          rows: [makeRow(block.header, true), ...block.rows.map(row => makeRow(row, false))],
        }),
        new Paragraph({ spacing: { after: 120 }, children: [] }),
      ]
    }

    case 'code': {
      const lines = block.text.replace(/\t/g, '    ').split('\n')
      return [
        new Paragraph({
          shading: { type: ShadingType.CLEAR, fill: COLORS.codeBackground, color: 'auto' },
          border: { left: { style: BorderStyle.SINGLE, size: 18, color: COLORS.accent, space: 8 } },
          indent: { left: 160, right: 120 },
          spacing: { before: 80, after: 200, line: 264 },
          children: lines.map((text, index) => new TextRun({ text: text || ' ', font: CODE_FONT, size: 19, break: index ? 1 : undefined })),
        }),
      ]
    }

    case 'quote':
      return block.blocks.flatMap(inner =>
        inner.type === 'paragraph'
          ? [new Paragraph({
              indent: { left: 480 },
              border: { left: { style: BorderStyle.SINGLE, size: 18, color: COLORS.border, space: 10 } },
              children: runs(docx, inner.inlines, { italics: true, color: COLORS.muted }),
            })]
          : renderBlock(docx, inner, context, 480))

    case 'rule':
      return [new Paragraph({
        spacing: { before: 120, after: 120 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: COLORS.border, space: 1 } },
        children: [],
      })]
  }
}

function renderList(docx: Docx, block: Extract<Block, { type: 'list' }>, context: Context, level: number): Child[] {
  const { Paragraph, TextRun } = docx
  const out: Child[] = []
  const instance = block.ordered ? ++context.orderedInstance : 0
  const numbering = (depth: number) => block.ordered
    ? { reference: 'numbers', level: Math.min(depth, 2), instance }
    : { reference: 'bullets', level: Math.min(depth, 2) }

  for (const item of block.items) {
    const [first, ...rest] = item.blocks
    const isTask = item.checked !== null
    const task = isTask ? [new TextRun({ text: item.checked ? '\u2611  ' : '\u2610  ' })] : []
    // A task item shows its checkbox instead of a bullet, with the same hanging indent.
    const marker = isTask
      ? { indent: { left: 540 + level * 360, hanging: 360 } }
      : { numbering: numbering(level) }
    if (first?.type === 'paragraph') {
      out.push(new Paragraph({ ...marker, spacing: { after: 60 }, children: [...task, ...runs(docx, first.inlines)] }))
    } else {
      out.push(new Paragraph({ ...marker, spacing: { after: 60 }, children: task }))
      if (first) rest.unshift(first)
    }
    for (const inner of rest) {
      if (inner.type === 'list') out.push(...renderList(docx, inner, context, level + 1))
      else out.push(...renderBlock(docx, inner, context, 540 + level * 360))
    }
  }
  if (level === 0) out.push(new Paragraph({ spacing: { after: 60 }, children: [] }))
  return out
}

/** Builds the Word document. Exported so tests and tools can inspect it without a browser. */
export function buildDocxDocument(docx: Docx, parsed: ParsedDocument, fallbackTitle = '') {
  const { Document, Paragraph, Footer, AlignmentType, BorderStyle, HeadingLevel, LevelFormat, PageNumber, TextRun } = docx
  const context: Context = { orderedInstance: 0 }

  const children: Child[] = []
  if (parsed.title) {
    children.push(new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun(parsed.title)] }))
  }
  for (const block of parsed.blocks) children.push(...renderBlock(docx, block, context))
  if (!children.length) children.push(new Paragraph({ children: [] }))

  const bulletLevels = ['\u2022', '\u25E6', '\u25AA'].map((text, level) => ({
    level,
    format: LevelFormat.BULLET,
    text,
    alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540 + level * 360, hanging: 270 } } },
  }))
  const numberFormats = [LevelFormat.DECIMAL, LevelFormat.LOWER_LETTER, LevelFormat.LOWER_ROMAN]
  const numberLevels = numberFormats.map((format, level) => ({
    level,
    format,
    text: `%${level + 1}.`,
    alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540 + level * 360, hanging: 360 } } },
  }))

  const heading = (id: string, name: string, size: number, before: number, after: number, outline: number, color = COLORS.heading) => ({
    id, name, basedOn: 'Normal', next: 'Normal', quickFormat: true,
    run: { size, bold: true, color, font: BODY_FONT },
    paragraph: { spacing: { before, after }, keepNext: true, keepLines: true, outlineLevel: outline },
  })

  return new Document({
    creator: 'Dabba',
    title: parsed.title ?? fallbackTitle,
    styles: {
      default: {
        document: {
          run: { font: BODY_FONT, size: 22, color: COLORS.ink },
          paragraph: { spacing: { after: 140, line: 288 } },
        },
      },
      paragraphStyles: [
        {
          id: 'Title', name: 'Title', basedOn: 'Normal', next: 'Normal', quickFormat: true,
          run: { size: 52, bold: true, color: '111827', font: BODY_FONT },
          paragraph: {
            spacing: { after: 280 },
            border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: COLORS.accent, space: 8 } },
          },
        },
        // The footer's own size, so the page-number fields match the text around them.
        { id: 'Footer', name: 'footer', basedOn: 'Normal', run: { size: 18, color: '6B7280' }, paragraph: { spacing: { after: 0 } } },
        heading('Heading1', 'heading 1', 34, 400, 140, 0),
        heading('Heading2', 'heading 2', 28, 300, 110, 1),
        heading('Heading3', 'heading 3', 24, 220, 90, 2, '374151'),
        heading('Heading4', 'heading 4', 22, 180, 70, 3, '374151'),
      ],
      characterStyles: [
        { id: 'Hyperlink', name: 'Hyperlink', run: { color: COLORS.link, underline: { type: 'single' } } },
      ],
    },
    numbering: {
      config: [
        { reference: 'bullets', levels: bulletLevels },
        { reference: 'numbers', levels: numberLevels },
      ],
    },
    sections: [{
      properties: {
        page: { margin: { top: 1247, bottom: 1247, left: PAGE_MARGIN, right: PAGE_MARGIN } },
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            style: 'Footer',
            alignment: AlignmentType.CENTER,
            children: [
              new TextRun({ text: 'Page ', size: 18, color: '6B7280' }),
              new TextRun({ children: [PageNumber.CURRENT], size: 18, color: '6B7280' }),
              new TextRun({ text: ' of ', size: 18, color: '6B7280' }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18, color: '6B7280' }),
            ],
          })],
        }),
      },
      children,
    }],
  })
}

export async function createDocxBlob(content: string, fallbackTitle = ''): Promise<Blob> {
  const docx = await import('docx')
  return docx.Packer.toBlob(buildDocxDocument(docx, parseDocument(content), fallbackTitle))
}
