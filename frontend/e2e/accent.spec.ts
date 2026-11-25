import { expect, test, type Page } from '@playwright/test'

async function openSettings(page: Page) {
  await page.addInitScript(() => localStorage.setItem('dabba-session-token', 'test-session'))
  await page.route('**/v1/**', route => route.request().url().includes('/identity/me')
    ? route.fulfill({ json: { id: 'u1', name: 'Test User', email: 'user@example.com', role: 'admin', createdAt: 0, updatedAt: 0 } })
    : route.fulfill({ json: [] }))
  await page.goto('/')
  await page.locator('button:has-text("Test User")').first().click()
  await page.getByText('Settings', { exact: true }).first().click()
}

const accent = (page: Page) =>
  page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--accent-rgb').trim())

test('people can choose their own accent color; Cancel undoes it and Save keeps it', async ({ page }) => {
  await openSettings(page)
  const original = await accent(page)

  // Previews live while Settings is open.
  await page.getByRole('radio', { name: 'Green' }).click()
  const green = await accent(page)
  expect(green).not.toBe(original)

  // Cancel restores the saved color.
  await page.getByRole('button', { name: 'Cancel' }).click()
  expect(await accent(page)).toBe(original)

  // Save keeps it, and a reload still has it (set before the app renders).
  await page.locator('button:has-text("Test User")').first().click()
  await page.getByText('Settings', { exact: true }).first().click()
  await page.getByRole('radio', { name: 'Green' }).click()
  await page.getByRole('button', { name: 'Save Settings' }).click()
  await expect.poll(() => accent(page)).toBe(green)
  await page.reload()
  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue('--accent-rgb'))).toBe(green)
})

test('a very light custom color is darkened so white button text stays readable', async ({ page }) => {
  await openSettings(page)
  await page.getByLabel('Custom color').fill('#ffee00')
  const [r, g, b] = (await accent(page)).split(' ').map(Number)
  const channel = (value: number) => { const c = value / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
  const luminance = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
  expect(1.05 / (luminance + 0.05)).toBeGreaterThanOrEqual(4.5)
})
