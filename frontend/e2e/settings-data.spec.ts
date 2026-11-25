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
      return route.fulfill({ json: { replies: 3, promptTokens: 1200, completionTokens: 345, totalTokens: 1545, byModel: [{ model: 'm-1', tokens: 1545, replies: 3, promptTokens: 1200, completionTokens: 345 }] } })
    }
    if (url.includes('/v1/conversations/') && request.method() === 'DELETE') {
      const id = url.split('/v1/conversations/')[1].split('?')[0]
      deletes.push(id)
      remaining = remaining.filter(item => item !== id)
      return route.fulfill({ status: 204, body: '' })
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
    return route.fulfill({ json: [] })
  })
  await page.goto('/')
  await page.locator('button:has-text("Test User")').first().click()
  await page.getByText('Settings', { exact: true }).first().click()
}

test('Usage shows what the server recorded, not an empty browser copy', async ({ page }) => {
  await openSettings(page, [])
  await page.getByRole('button', { name: 'Usage' }).click()
  const dialog = page.getByRole('dialog', { name: 'Settings' })
  await expect(dialog).toContainText('1,545')
  await expect(dialog).toContainText('Total Tokens')
  await expect(dialog).toContainText('3 replies')
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
