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

test('login and signup keep the header controls together at 320px', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 560 })
  for (const path of ['/login', '/signup']) {
    await page.goto(path)
    const header = page.locator('main header')
    const home = header.getByRole('button', { name: 'Dabba home' })
    const theme = header.getByRole('button', { name: /Switch to/ })
    const tryDabba = header.getByRole('link', { name: 'Try Dabba', exact: true })
    await expect(home).toBeInViewport()
    await expect(theme).toBeInViewport()
    await expect(tryDabba).toBeInViewport()
    await expect(page.getByLabel(path === '/login' ? 'Email' : 'Name', { exact: true })).not.toBeFocused()
    const controls = await Promise.all([home.boundingBox(), theme.boundingBox(), tryDabba.boundingBox()])
    expect(controls.map(control => control && [control.y, control.height])).toEqual(
      Array(3).fill([controls[0]?.y, 44]),
    )
    expect(controls[2]!.x + controls[2]!.width).toBeLessThan(320)
  }
})
