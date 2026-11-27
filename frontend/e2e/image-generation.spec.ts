import { expect, test } from '@playwright/test'
import { FLUX_IMAGE_MODEL } from '../src/lib/models'

test('sending a prompt with FLUX selected generates an image', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('dabba-session-token', 'test-session'))
  await page.route('**/v1/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/identity/me')) {
      return route.fulfill({ json: { id: 'owner', name: 'Owner', email: 'owner@example.com', role: 'admin' } })
    }
    if (path === '/v1/agent/models') {
      return route.fulfill({ json: { models: [{ id: FLUX_IMAGE_MODEL, name: 'FLUX.1-dev (Image)', provider: 'nvidia', tier: 'high', has_key: true }] } })
    }
    if (path === '/v1/images/generations') {
      expect(route.request().postDataJSON()).toMatchObject({ prompt: 'A mountain at sunset', model: FLUX_IMAGE_MODEL })
      return route.fulfill({ json: { data: [{ b64_json: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGh4AAAAASUVORK5CYII=' }] } })
    }
    expect(path).not.toBe('/v1/chat/completions')
    return route.fulfill({ json: [] })
  })

  await page.goto('/')
  await page.getByRole('button', { name: /Change model/ }).click()
  await page.getByRole('dialog', { name: 'Choose model' }).getByRole('button', { name: /FLUX.1-dev/ }).click()
  const prompt = page.getByPlaceholder('Describe the image to generate…')
  await prompt.fill('A mountain at sunset')
  await prompt.press('Enter')
  await expect(page.getByRole('img', { name: /generated/ })).toBeVisible()
})
