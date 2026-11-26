import { expect, test, type Page } from '@playwright/test'

// A catalogue as big as the real one (43 models) so the picker has to scroll.
const PROVIDERS = ['anthropic', 'openai', 'google', 'nvidia', 'huggingface', 'ollama']
const MODELS = Array.from({ length: 43 }, (_, i) => ({
  id: `m-${i}`, name: `Model ${i + 1}`, provider: PROVIDERS[i % 6], tier: ['low', 'medium', 'high'][i % 3],
  description: 'Early-access reasoning model for agentic, coding and long-context work',
  has_key: true, keySource: 'API_KEY', contextWindow: 128000,
}))

async function signedIn(page: Page) {
  await page.addInitScript(() => localStorage.setItem('dabba-session-token', 'test-session'))
  await page.route('**/v1/**', route => {
    const url = route.request().url()
    if (url.includes('/identity/me')) {
      return route.fulfill({ json: { id: 'u1', name: 'Test User', email: 'user@example.com', role: 'admin', createdAt: 0, updatedAt: 0 } })
    }
    if (url.includes('/v1/agent/models')) return route.fulfill({ json: { models: MODELS, current: 'm-1', effort: 'medium' } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/')
}

for (const height of [923, 560, 420]) {
  test(`the model menu stays fully on screen in a ${height}px tall window`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height })
    await signedIn(page)
    await page.getByRole('button', { name: /Change model/ }).click()
    const menu = page.getByRole('dialog', { name: 'Choose model' })
    await expect(menu).toBeVisible()
    await expect.poll(async () => {
      const box = await menu.boundingBox()
      return !!box && box.y >= 60 && box.y + box.height <= height
    }).toBe(true)
  })
}

test('a model or effort picked in the header is kept when Settings is opened and saved', async ({ page }) => {
  await signedIn(page)
  await page.getByRole('button', { name: /Change effort/ }).click()
  await page.getByRole('dialog', { name: 'Reasoning effort' }).getByRole('button').last().click()
  const effort = () => page.evaluate(() => JSON.parse(localStorage.getItem('dabba-settings') ?? '{}').effort)
  const picked = await effort()

  const sidebar = page.getByTitle('Open sidebar (Ctrl+B)')
  if (await sidebar.isVisible()) await sidebar.click()
  await page.locator('button:has-text("Test User")').first().click()
  await page.getByText('Settings', { exact: true }).first().click()
  const navigation = page.getByRole('button', { name: 'Open settings navigation' })
  if (await navigation.isVisible()) await navigation.click()
  await page.getByRole('button', { name: 'Model & Params' }).click()
  // The dialog shows what the header picked, not the value from when the app loaded...
  await expect(page.locator('select').first()).toHaveValue(picked)
  // ...and saving does not write the old value back.
  await page.getByRole('button', { name: 'Save Settings' }).click()
  await expect.poll(effort).toBe(picked)
})
