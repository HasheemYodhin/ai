import { expect, test } from '@playwright/test'

test('signed-out visitors can log in, sign up, and open guest chat from home', async ({ page }) => {
  await page.route('**/v1/guest/status**', route => route.fulfill({ json: { available: true, remaining: 5, limit: 5 } }))
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: /Dabba/ })).toBeVisible()
  await page.getByRole('link', { name: 'Log in' }).first().click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Log in', level: 1 })).toBeVisible()

  await page.getByRole('button', { name: 'Create now' }).click()
  await expect(page).toHaveURL(/\/signup$/)

  await page.getByRole('link', { name: 'Try Dabba without an account' }).click()
  await expect(page).toHaveURL(/\/try$/)
  await expect(page.getByRole('heading', { name: 'Try Dabba' })).toBeVisible()
})

test('a protected address shows sign-in and preserves the URL', async ({ page }) => {
  await page.goto('/c/saved-chat')
  await expect(page.getByRole('heading', { name: 'Log in', level: 1 })).toBeVisible()
  await expect(page).toHaveURL(/\/c\/saved-chat$/)
})

test('unknown addresses show the 404 page with a way home', async ({ page }) => {
  await page.goto('/definitely-not-a-page')
  await expect(page.getByRole('heading', { name: "This page doesn't exist" })).toBeVisible()
  await page.getByRole('button', { name: 'Go to the home page' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { level: 1, name: /Dabba/ })).toBeVisible()
})

test('the theme toggle switches light and dark on the public pages and remembers the choice', async ({ page }) => {
  await page.addInitScript(() => {
    // Seed once so a reload keeps whatever the visitor picked.
    if (!localStorage.getItem('dabba-theme')) localStorage.setItem('dabba-theme', 'light')
  })
  await page.goto('/')
  const html = page.locator('html')
  await expect(html).toHaveClass(/light/)

  await page.getByRole('button', { name: 'Switch to dark mode' }).click()
  await expect(html).toHaveClass(/dark/)

  // The choice carries over to the login page and survives a reload.
  await page.getByRole('link', { name: 'Log in' }).first().click()
  await expect(page).toHaveURL(/\/login$/)
  await page.reload()
  await expect(html).toHaveClass(/dark/)

  await page.getByRole('button', { name: 'Switch to light mode' }).click()
  await expect(html).toHaveClass(/light/)
})
