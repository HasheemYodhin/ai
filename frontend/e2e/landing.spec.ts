import { expect, test } from '@playwright/test'

test('landing page leads to sign up and log in', async ({ page, isMobile }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: /One self hosted workspace/ })).toBeVisible()
  await expect(page).toHaveScreenshot('landing.png', {
    fullPage: true,
    animations: 'disabled',
    maxDiffPixelRatio: 0.02,
  })

  await page.getByRole('button', { name: 'Get started' }).click()
  await expect(page).toHaveURL(/\/signup$/)
  await expect(page.getByRole('heading', { name: 'Create your account' })).toBeVisible()

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
