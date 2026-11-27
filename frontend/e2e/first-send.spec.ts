import { expect, test } from '@playwright/test'

// The model and the skill lookup are slow here on purpose: the first message
// in a new chat must still appear right away instead of the welcome screen
// staying up until the first word of the reply arrives.
test('the first message shows immediately, even when the model is slow', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('dabba-session-token', 'test-session'))
  await page.route('**/v1/**', async route => {
    const url = route.request().url()
    if (url.includes('/identity/me')) {
      return route.fulfill({ json: { id: 'u1', name: 'Test User', email: 'user@example.com', role: 'admin', createdAt: 0, updatedAt: 0 } })
    }
    if (url.includes('/skills/match')) {
      await new Promise(resolve => setTimeout(resolve, 4000))
      return route.fulfill({ json: { skill: null } })
    }
    if (url.includes('/v1/chat/completions')) {
      const body = route.request().postData() ?? ''
      const sse = (text: string) => `data: ${JSON.stringify({ choices: [{ delta: { content: text }, finish_reason: 'stop' }] })}\n\ndata: [DONE]\n\n`
      if (body.includes('chat title')) return route.fulfill({ contentType: 'text/event-stream', body: sse('Greeting') })
      await new Promise(resolve => setTimeout(resolve, 3000))
      return route.fulfill({ contentType: 'text/event-stream', body: sse('Hello there') })
    }
    return route.fulfill({ json: [] })
  })

  await page.goto('/')
  const box = page.getByPlaceholder('Ask anything…')
  await box.fill('Hi')
  await box.press('Enter')

  // Well before the 3s model delay: the user's message is on screen, the welcome screen is gone.
  const userMessage = page.getByRole('main').getByRole('paragraph').filter({ hasText: /^Hi$/ })
  await expect(userMessage).toBeVisible({ timeout: 1500 })
  await expect(page.getByRole('heading', { name: 'Chat, write code or make an image' })).toHaveCount(0)

  // The reply still arrives, and the skill lookup did not hold it back for its full 4s.
  await expect(page.getByText('Hello there')).toBeVisible({ timeout: 9000 })
})
