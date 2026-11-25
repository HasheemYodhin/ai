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
    // Streamed like the server: text pieces, then a done event.
    const events = [{ delta: 'Answer ' }, { delta: String(used) }, { done: true, remaining: 5 - used }]
    return route.fulfill({
      contentType: 'text/event-stream',
      body: ': keepalive\n\n' + events.map(e => `data: ${JSON.stringify(e)}\n\n`).join(''),
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
  // No prompt counter is shown to guests.
  await expect(page.getByText(/free prompts? (left|used)/)).toHaveCount(0)

  // The 6th prompt opens the sign up gate instead of sending.
  await box.fill('Question 6')
  await box.press('Enter')
  const gate = page.getByRole('dialog', { name: "You've used your 5 free prompts" })
  await expect(gate).toBeVisible()
  expect(used).toBe(5)

  await gate.getByRole('button', { name: 'Create your account' }).click()
  await expect(page).toHaveURL(/\/signup$/)
})

test('a failed reply can be retried without repeating the question', async ({ page }) => {
  let calls = 0
  await page.route('**/v1/guest/status**', route => route.fulfill({ json: { available: true, remaining: 5, limit: 5 } }))
  await page.route('**/v1/guest/chat', route => {
    calls += 1
    const events = calls === 1
      ? [{ error: "Dabba couldn't answer just now. Try again in a moment.", remaining: 5 }]
      : [{ delta: 'Recovered answer' }, { done: true, remaining: 4 }]
    return route.fulfill({ contentType: 'text/event-stream', body: events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('') })
  })

  await page.goto('/try')
  const box = page.getByLabel('Message Dabba')
  await box.fill('Hello there')
  await box.press('Enter')
  await expect(page.getByRole('alert')).toContainText("Dabba couldn't answer just now")
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Recovered answer')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Hello there', { exact: true })).toHaveCount(1)
})
