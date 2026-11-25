import { expect, test, type Page } from '@playwright/test'

// Conversations live on the server, not in the browser, so Usage, Export and
// Clear History must all go through the server. The API is mocked.
async function openSettings(page: Page, deletes: string[]) {
  let remaining = ['c1', 'c2', 'c3']
  await page.addInitScript(() => localStorage.setItem('dabba-session-token', 'test-session'))
  await page.route('**/v1/**', async route => {
    const request = route.request()
    const url = request.url()
    if (url.includes('/identity/me')) {
      return route.fulfill({ json: { id: 'u1', name: 'Test User', email: 'user@example.com', role: 'admin', createdAt: 0, updatedAt: 0 } })
    }
    if (url.includes('/platform/usage')) {
      return route.fulfill({ json: {
        replies: 3, promptTokens: 1200, completionTokens: 345, totalTokens: 1545,
        byModel: [{ model: 'm-1', tokens: 1545, replies: 3, promptTokens: 1200, completionTokens: 345 }],
        limits: [
          { label: '5-hour', windowHours: 5, usedTokens: 100, limitTokens: 250000 },
          { label: 'Daily', windowHours: 24, usedTokens: 300, limitTokens: 1000000 },
          { label: 'Weekly', windowHours: 168, usedTokens: 1545, limitTokens: 4000000 },
        ],
      } })
    }
    if (url.includes('/v1/conversations/') && request.method() === 'DELETE') {
      const id = url.split('/v1/conversations/')[1].split('?')[0]
      deletes.push(id)
      remaining = remaining.filter(item => item !== id)
      return route.fulfill({ status: 204, body: '' })
    }
    if (url.endsWith('/v1/conversations/c1')) {
      return route.fulfill({ json: {
        id: 'c1', title: 'Chat c1', createdAt: 1, updatedAt: 1,
        messages: [{ id: 'reply', role: 'assistant', timestamp: 1, content: [
          '| Problem | Likely cause | Solution |',
          '| --- | --- | --- |',
          '| Missing command | Python is unavailable | Check `a-very-long-command-name-without-spaces` |',
          '',
          '```python',
          'print(1)',
          '```',
        ].join('\n') }],
      } })
    }
    if (url.includes('/v1/conversations?')) {
      const withMessages = url.includes('include_messages=true')
      return route.fulfill({
        json: {
          conversations: remaining.map((id, index) => ({
            id, title: `Chat ${id}`, createdAt: 1, updatedAt: 1 + index, pinned: false, messageCount: 2 + index,
            ...(withMessages ? { messages: [{ id: `${id}-a`, role: 'user', content: 'hello', timestamp: 1 }, { id: `${id}-b`, role: 'assistant', content: 'hi', timestamp: 2 }] } : {}),
          })),
        },
      })
    }
    if (url.endsWith('/v1/code/languages')) {
      return route.fulfill({ json: { languages: ['python'], unavailableReason: null } })
    }
    return route.fulfill({ json: [] })
  })
  await page.goto('/')
  const profile = page.locator('button:has-text("Test User")').first()
  const sidebar = page.getByTitle('Open sidebar (Ctrl+B)')
  await expect(sidebar.or(profile).filter({ visible: true })).toBeVisible()
  if (await sidebar.isVisible()) await sidebar.click()
  await profile.click()
  await page.getByText('Settings', { exact: true }).first().click()
  const navigation = page.getByRole('button', { name: 'Open settings navigation' })
  if (await navigation.isVisible()) await navigation.click()
}

test('Usage shows what the server recorded, not an empty browser copy', async ({ page }) => {
  await openSettings(page, [])
  await page.getByRole('button', { name: 'Usage' }).click()
  const dialog = page.getByRole('dialog', { name: 'Settings' })
  await expect(dialog).toContainText('1,545')
  await expect(dialog).toContainText('Total Tokens')
  await expect(dialog).toContainText('3 replies')
  for (const label of ['5-hour', 'Daily', 'Weekly']) {
    await expect(dialog.getByRole('progressbar', { name: `${label} chat token usage` })).toBeVisible()
  }
})

test('A mobile reply keeps its table inside the chat and uses the selected Run accent', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 799 })
  await openSettings(page, [])
  await page.getByRole('button', { name: 'Close settings navigation' }).click()
  await page.getByRole('radio', { name: 'Teal' }).click()
  const save = page.getByRole('button', { name: 'Save Settings' })
  await expect(save).toHaveCSS('background-color', 'rgb(15, 124, 138)')
  const accent = await save.evaluate(button => getComputedStyle(button).backgroundColor)
  await save.click()
  await expect(page.getByRole('dialog', { name: 'Settings' })).toBeHidden()
  const chat = page.getByText('Chat c1', { exact: true }).first()
  if (!(await chat.isVisible())) await page.getByTitle('Open sidebar (Ctrl+B)').click()
  await chat.click()
  const table = page.getByRole('table')
  await expect(table).toBeVisible()
  expect(await table.evaluate(element => element.getBoundingClientRect().right)).toBeLessThan(400)
  const run = page.getByRole('button', { name: 'Run', exact: true })
  await expect(run).toBeEnabled()
  await expect(run).toHaveCSS('background-color', accent)
})

test('Export downloads the conversations stored on the server', async ({ page }) => {
  await openSettings(page, [])
  await page.getByRole('button', { name: 'Data Controls' }).click()
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: /Export Conversations/ }).click(),
  ])
  expect(download.suggestedFilename()).toMatch(/^dabba-conversations-export-/)
})

test('Clear History deletes the conversations on the server, and only after confirmation', async ({ page }) => {
  const deletes: string[] = []
  await openSettings(page, deletes)
  await page.getByRole('button', { name: 'Data Controls' }).click()

  page.once('dialog', dialog => dialog.dismiss())
  await page.getByRole('button', { name: /Clear History/ }).click()
  expect(deletes).toEqual([])

  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: /Clear History/ }).click()
  await expect.poll(() => [...deletes].sort()).toEqual(['c1', 'c2', 'c3'])
})
