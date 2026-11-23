import { expect, test } from '@playwright/test'

test('authentication screen is usable on desktop and mobile', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Log in', exact: true })).toBeVisible()
  await page.getByRole('tab', { name: 'Sign up' }).click()
  await expect(page.getByRole('heading', { name: 'Create your account' })).toBeVisible()
  await expect(page.getByPlaceholder('At least 10 characters')).toBeVisible()
  await expect(page).toHaveScreenshot('auth-signup.png', {
    animations: 'disabled',
    maxDiffPixelRatio: 0.02,
  })
})
