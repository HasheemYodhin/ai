import { expect, test } from '@playwright/test'

test('authentication screen is usable on desktop and mobile', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Dabba' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Log in' })).toBeVisible()
  await page.getByRole('button', { name: 'Sign up' }).click()
  await expect(page.getByPlaceholder('At least 10 characters')).toBeVisible()
  await expect(page).toHaveScreenshot('auth-signup.png', {
    animations: 'disabled',
    maxDiffPixelRatio: 0.02,
  })
})
