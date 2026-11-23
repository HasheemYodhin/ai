import { expect, test } from '@playwright/test'

test('landing page leads to sign up and log in', async ({ page, isMobile }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: /Introducing Dabba/ })).toBeVisible()
  await expect(page).toHaveScreenshot('landing.png', {
    fullPage: true,
    animations: 'disabled',
    maxDiffPixelRatio: 0.02,
  })

  await page.getByRole('main').getByRole('button', { name: 'Try Dabba' }).first().click()
  await expect(page).toHaveURL(/\/try$/)
  await expect(page.getByRole('heading', { name: 'Try Dabba' })).toBeVisible()

  await page.goBack()
  await expect(page).toHaveURL(/\/$/)
  if (isMobile) {
    // Phones reach Log in through the full height menu.
    await page.getByRole('button', { name: 'Open menu' }).click()
    await page.locator('#mobile-menu').getByRole('button', { name: 'Log in' }).click()
  } else {
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Log in' }).click()
  }
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
})

test('unknown addresses show the 404 page with a way home', async ({ page }) => {
  await page.goto('/definitely-not-a-page')
  await expect(page.getByRole('heading', { name: "This page doesn't exist" })).toBeVisible()
  await page.getByRole('button', { name: 'Go to the home page' }).click()
  await expect(page).toHaveURL(/\/$/)
})

test('a sample prompt chip fills the free chat without sending it', async ({ page }) => {
  let sent = 0
  await page.route('**/v1/guest/status**', route => route.fulfill({ json: { available: true, remaining: 5, limit: 5 } }))
  await page.route('**/v1/guest/chat', route => { sent += 1; return route.fulfill({ status: 500 }) })

  await page.goto('/')
  const chip = page.getByRole('button', { name: 'Write a Python function that removes duplicates from a list' })
  await chip.scrollIntoViewIfNeeded()
  await chip.click()
  await expect(page).toHaveURL(/\/try$/)
  await expect(page.getByLabel('Message Dabba')).toHaveValue('Write a Python function that removes duplicates from a list')
  expect(sent).toBe(0)
})
