import { expect, test } from '@playwright/test'

test.use({ locale: 'en-US', timezoneId: 'Asia/Kolkata' })

test('find, save, branch, recover and share from the chat', async ({ page }) => {
  const shareId = 'q'.repeat(32)
  let shared = false
  let saved = false
  const chat = {
    id: 'c1', title: 'Example chat', createdAt: 1, updatedAt: 2, revision: 1,
    messages: [
      { id: 'm1', role: 'user', content: 'First needle', timestamp: Date.parse('2026-11-27T12:30:00Z') },
      { id: 'm2', role: 'assistant', content: 'Second needle', timestamp: Date.parse('2026-11-27T12:32:00Z'), sources: [
        { kind: 'web', title: 'Example source', url: 'https://example.com' },
      ] },
      { id: 'm3', role: 'assistant', content: 'Partial reply', timestamp: 3, interrupted: true, recoveryRequestId: 'reply-fixture' },
    ],
  }
  let branch: unknown
  await page.addInitScript(() => localStorage.setItem('dabba-session-token', 'test-session'))
  await page.route('**/v1/**', async route => {
    const request = route.request()
    const { pathname } = new URL(request.url())
    if (pathname.endsWith('/identity/me')) return route.fulfill({ json: { id: 'u1', name: 'Tester', email: 'user@example.com', role: 'member', createdAt: 0, updatedAt: 0 } })
    if (pathname === '/v1/conversations') return route.fulfill({ json: { conversations: [chat] } })
    if (pathname === '/v1/conversations/saved') return route.fulfill({ json: { items: saved ? [{ conversation_id: 'c1', message_id: 'm2', title: chat.title, snippet: 'Second needle' }] : [] } })
    if (pathname === '/v1/conversations/c1/saved/m2') {
      saved = request.method() === 'PUT'
      return route.fulfill({ status: 204 })
    }
    if (pathname === '/v1/conversations/recovery') return route.fulfill({ json: { status: 'completed', result: { content: 'Recovered complete reply', model: 'dabba' } } })
    if (pathname === '/v1/conversations/c1/shares') {
      if (request.method() === 'POST') {
        expect(request.postDataJSON().messageIds).toEqual(['m2'])
        shared = true
        return route.fulfill({ status: 201, json: { id: shareId, created_at: 1 } })
      }
      return route.fulfill({ json: { items: [] } })
    }
    if (pathname === `/v1/conversations/c1/shares/${shareId}`) {
      shared = false
      return route.fulfill({ status: 204 })
    }
    if (pathname === `/v1/conversations/public/shares/${shareId}`) {
      return shared
        ? route.fulfill({ json: { title: chat.title, messages: [{ role: 'assistant', content: 'Second needle' }] } })
        : route.fulfill({ status: 404, json: { detail: 'Unavailable' } })
    }
    if (pathname === '/v1/conversations/c1') {
      if (request.method() === 'PUT') {
        chat.messages = request.postDataJSON().messages
        return route.fulfill({ json: { revision: ++chat.revision } })
      }
      return route.fulfill({ json: chat })
    }
    if (pathname.startsWith('/v1/conversations/') && request.method() === 'PUT') {
      branch = request.postDataJSON()
      return route.fulfill({ json: { revision: 1 } })
    }
    return route.fulfill({ json: [] })
  })

  await page.goto('/c/c1')
  const reply = page.locator('#message-m2')
  await expect(reply).toBeVisible()
  const sentTime = page.locator('#message-m1 time')
  const replyTime = reply.locator('time')
  await expect(sentTime).toBeVisible()
  await expect(sentTime).toHaveText('06:00 PM')
  await expect(replyTime).toBeVisible()
  await expect(replyTime).toHaveText('06:02 PM')
  await expect(replyTime).toHaveAttribute('datetime', '2026-11-27T12:32:00.000Z')
  await page.getByRole('button', { name: 'Find in chat', exact: true }).click()
  const search = page.getByRole('textbox', { name: 'Search this chat' })
  await search.fill('needle')
  await search.press('Enter')
  await search.press('Enter')
  await expect(page.getByRole('search').getByRole('status')).toHaveText('2/2')
  await page.getByRole('button', { name: 'Close find' }).click()
  await reply.getByText('Sources (1)').click()
  await expect(reply.getByRole('link', { name: 'Example source' })).toHaveAttribute('href', 'https://example.com')
  await reply.getByRole('button', { name: 'Save message', exact: true }).click()
  await expect(reply.getByRole('button', { name: 'Remove saved message' })).toBeVisible()
  await page.getByRole('button', { name: 'Saved messages', exact: true }).click()
  const bookmarks = page.getByRole('dialog', { name: 'Saved messages' })
  await bookmarks.getByRole('button', { name: /Second needle/ }).click()
  await expect(reply).toBeFocused()

  await page.getByRole('button', { name: 'Recover reply' }).click()
  await expect(page.getByText('Recovered complete reply', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Share chat', exact: true }).click()
  const sharing = page.getByRole('dialog', { name: 'Share chat' })
  await sharing.getByRole('checkbox', { name: /Second needle/ }).check()
  await sharing.getByRole('button', { name: 'Preview selection' }).click()
  await expect(sharing.getByText('First needle')).toHaveCount(0)
  await sharing.getByRole('button', { name: 'Create public link' }).click()
  await expect(sharing.getByRole('textbox', { name: 'Share link' })).toHaveValue(new RegExp(`/share/${shareId}$`))
  await sharing.getByRole('button', { name: 'Revoke link' }).click()
  await expect(sharing.getByRole('button', { name: 'Revoke link' })).toHaveCount(0)
  await sharing.getByRole('button', { name: 'Close', exact: true }).click()

  await reply.getByRole('button', { name: 'Branch from this message' }).click()
  await expect.poll(() => branch).toEqual(expect.objectContaining({
    messages: [expect.objectContaining({ id: 'm1' }), expect.objectContaining({ id: 'm2' })],
  }))
  await expect(page.getByText('Recovered complete reply', { exact: true })).toHaveCount(0)
  await page.goto(`/share/${shareId}`)
  await expect(page.getByRole('alert')).toHaveText('This shared chat is unavailable.')
})
