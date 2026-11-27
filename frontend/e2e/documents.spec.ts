import { expect, test } from '@playwright/test'

// A reply like a model's: a chat lead-in, a titled document, and a closing offer.
const REPLY = [
  'Sure! Here is the document you asked for:',
  '',
  '# Onboarding Checklist',
  '',
  'A short guide for **new engineers**.',
  '',
  '## Week one',
  '',
  '- Get repository access',
  '- Set up the local environment',
  '',
  '## Tasks',
  '',
  '| Task | Owner |',
  '| --- | --- |',
  '| Laptop setup | IT |',
  '',
  'Let me know if you want changes!',
].join('\n')

const SUMMARY = 'A week-one onboarding checklist with responsibilities for new engineers.'

test('logs progress and shows one short summary beside all five document downloads', async ({ page }) => {
  let modelPrompt = ''
  let finishDraft!: () => void
  const drafting = new Promise<void>(resolve => { finishDraft = resolve })
  let finishPdfLoad!: () => void
  const pdfLoading = new Promise<void>(resolve => { finishPdfLoad = resolve })
  await page.route('**/src/lib/documents/pdf.ts*', async route => {
    await pdfLoading
    await route.continue()
  })
  await page.addInitScript(() => localStorage.setItem('dabba-session-token', 'test-session'))
  await page.route('**/v1/**', async route => {
    const request = route.request()
    const url = request.url()
    if (url.includes('/identity/me')) {
      return route.fulfill({ json: { id: 'u1', name: 'Test User', email: 'user@example.com', role: 'admin', createdAt: 0, updatedAt: 0 } })
    }
    if (url.includes('/skills/match')) return route.fulfill({ json: { skill: null } })
    if (url.includes('/v1/chat/completions')) {
      const sse = (text: string) => `data: ${JSON.stringify({ choices: [{ delta: { content: text, reasoning_content: 'Private file draft' }, finish_reason: 'stop' }] })}\n\ndata: [DONE]\n\n`
      const isTitleRequest = (request.postData() ?? '').includes('chat title')
      if (!isTitleRequest) modelPrompt = request.postData() ?? ''
      if (!isTitleRequest) await drafting
      return route.fulfill({ contentType: 'text/event-stream', body: sse(isTitleRequest ? 'Checklist' : `Chat summary: ${SUMMARY}\n\n${REPLY}`) })
    }
    if (url.includes('/v1/conversations?')) return route.fulfill({ json: { conversations: [] } })
    return route.fulfill({ json: [] })
  })

  await page.goto('/')
  const box = page.getByPlaceholder('Ask anything…')
  await box.fill('Please create a PDF, Word document, Excel workbook, PowerPoint and Markdown file for an onboarding checklist using the Technical template')
  await box.press('Enter')
  const progress = page.getByRole('status', { name: 'File preparation' })
  const log = page.getByRole('list', { name: 'File preparation log' })
  const formats = ['PDF', 'Word', 'Excel', 'PowerPoint', 'Markdown']
  try {
    await expect(progress).toHaveText('Drafting document content…')
    await expect(log.getByRole('listitem')).toHaveCount(formats.length)
    for (const name of formats) {
      await expect(log.getByRole('listitem').filter({ hasText: name })).toContainText('Queued')
    }
    finishDraft()
    await expect(progress).toHaveText('Building PDF…')
  } finally {
    finishDraft()
    finishPdfLoad()
  }

  // Named after the document's own title, not after the request. The libraries load on demand, so allow time.
  const links = page.locator('a[download]')
  await expect(links).toHaveCount(5, { timeout: 60_000 })
  for (const extension of ['pdf', 'docx', 'xlsx', 'pptx', 'md']) {
    await expect(page.locator(`a[download="onboarding-checklist.${extension}"]`)).toBeVisible()
  }
  await expect(progress).toHaveText('Files ready')
  await progress.click()
  for (const name of formats) {
    await expect(log.getByRole('listitem').filter({ hasText: name })).toContainText('Ready')
  }
  expect(modelPrompt).toContain('Document template: Technical')
  expect(modelPrompt).toContain('Chat summary:')
  await expect(page.getByText(SUMMARY, { exact: true })).toHaveCount(1)
  await expect(page.getByRole('main').getByText('Get repository access', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('main').getByText('Thinking', { exact: true })).toHaveCount(0)

  // The Markdown file is the document only: no lead-in, no closing offer.
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('a[download="onboarding-checklist.md"]').click(),
  ])
  const stream = await download.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream) chunks.push(Buffer.from(chunk))
  const markdown = Buffer.concat(chunks).toString('utf8')
  expect(markdown.startsWith('# Onboarding Checklist')).toBe(true)
  expect(markdown).not.toContain('Sure!')
  expect(markdown).not.toContain('Let me know')
  expect(markdown).not.toContain(SUMMARY)
  expect(markdown.endsWith('\n')).toBe(true)
})
