import { expect, test } from '@playwright/test'

test('authentication screen is usable on desktop and mobile', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Log in', level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Log in', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Create now' }).click()
  await expect(page.getByRole('heading', { name: 'Create an account', level: 1 })).toBeVisible()
  await expect(page.getByPlaceholder('At least 10 characters')).toBeVisible()
  await expect(page).toHaveScreenshot('auth-signup.png', {
    animations: 'disabled',
    maxDiffPixelRatio: 0.02,
  })
})
