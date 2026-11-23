import { expect, test } from '@playwright/test'

test('landing page leads to sign up and log in', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: /Your AI workspace/ })).toBeVisible()
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
  await page.getByRole('button', { name: 'Log in' }).first().click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
})
