import { expect, test } from '@playwright/test'

// The guest API is mocked so the test doesn't need a model provider. The mock
// mirrors the server: 5 free prompts, then 429 guest_limit_reached.
test('guests get 5 free prompts, then are asked to sign up', async ({ page }) => {
  let used = 0
  await page.route('**/v1/guest/status**', route => route.fulfill({
    json: { available: true, remaining: 5 - used, limit: 5 },
  }))
  await page.route('**/v1/guest/chat', route => {
    if (used >= 5) {
      return route.fulfill({ status: 429, json: { code: 'guest_limit_reached', remaining: 0 } })
    }
    used += 1
    return route.fulfill({
      contentType: 'text/event-stream',
      body: `data: ${JSON.stringify({ content: `Answer ${used}`, remaining: 5 - used })}\n\n`,
    })
  })

  await page.goto('/try')
  // The model is never named; guests only see "Auto".
  await expect(page.getByText('Auto', { exact: true })).toBeVisible()
  await expect(page.getByText(/Nemotron/)).toHaveCount(0)

  const box = page.getByLabel('Message Dabba')
  for (let i = 1; i <= 5; i += 1) {
    await box.fill(`Question ${i}`)
    await box.press('Enter')
    // The first reply lazily loads the Markdown renderer, which is slow on a cold dev server.
    await expect(page.getByText(`Answer ${i}`)).toBeVisible({ timeout: 15_000 })
  }
  await expect(page.getByText('5 of 5 free prompts used. Sign up to save your chats.')).toBeVisible()

  // The 6th prompt opens the sign up gate instead of sending.
  await box.fill('Question 6')
  await box.press('Enter')
  const gate = page.getByRole('dialog', { name: "You've used your 5 free prompts" })
  await expect(gate).toBeVisible()
  expect(used).toBe(5)

  await gate.getByRole('button', { name: 'Create your account' }).click()
  await expect(page).toHaveURL(/\/signup$/)
})
