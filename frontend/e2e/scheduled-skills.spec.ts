import { expect, test } from '@playwright/test'

// Store the wall-clock time with its named zone.
test.use({ timezoneId: 'Asia/Kolkata' })

test('the daily new words quick start creates a timezone-aware schedule and shows each run\'s result', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('dabba-session-token', 'test-session'))
  const models = [{ id: 'm-1', name: 'Test model', provider: 'nvidia', tier: 'low', description: '', has_key: true }]
  let schedules: Record<string, unknown>[] = []
  let runs: Record<string, unknown>[] = []
  let created: Record<string, unknown> = {}
  let startedAt = 0

  await page.route('**/v1/**', async route => {
    const request = route.request()
    const url = request.url()
    if (url.includes('/identity/me')) {
      return route.fulfill({ json: { id: 'u1', name: 'Test User', email: 'user@example.com', role: 'admin', createdAt: 0, updatedAt: 0 } })
    }
    if (url.includes('/v1/agent/models')) return route.fulfill({ json: { models, current: 'm-1', effort: 'medium' } })
    if (url.includes('/scheduled-skills/runs')) {
      // The run finishes on the server a few seconds after it starts.
      runs = runs.map(item => item.status !== 'completed' && Date.now() - startedAt > 3000
        ? { ...item, status: 'completed', output: { content: '1. **ephemeral** lasting a very short time' } }
        : item)
      return route.fulfill({ json: { runs } })
    }
    if (url.endsWith('/scheduled-skills') && request.method() === 'POST') {
      created = JSON.parse(request.postData() ?? '{}')
      schedules = [{ id: 's1', createdAt: 1, updatedAt: 1, enabled: true, weekdays: [], nextRunAt: Date.now() + 3_600_000, ...created }]
      return route.fulfill({ status: 201, json: schedules[0] })
    }
    if (url.endsWith('/scheduled-skills')) return route.fulfill({ json: { schedules } })
    if (url.includes('/scheduled-skills/s1/run')) {
      startedAt = Date.now()
      const run = { id: 'r1', scheduleId: 's1', status: 'queued', triggeredBy: 'manual', startedAt, output: null }
      runs = [run]
      return route.fulfill({ status: 202, json: run })
    }
    if (url.includes('/skills')) return route.fulfill({ json: { skills: [] } })
    return route.fulfill({ json: [] })
  })

  await page.goto('/scheduled-skills')
  await page.getByLabel('Words per day').selectOption('5')
  await page.getByRole('button', { name: 'Use this template' }).click()
  await expect(page.getByLabel('Time of day')).toHaveValue('08:00')
  await page.getByRole('textbox', { name: 'Schedule time zone' }).fill('Asia/Kolkata')
  await page.getByRole('button', { name: 'Create schedule' }).click()

  await expect.poll(() => created.timeOfDay).toBe('08:00')
  expect(created.timeZone).toBe('Asia/Kolkata')
  expect(created.cadence).toBe('daily')
  expect(String(created.instructions)).toContain('5 new English vocabulary words')
  await expect(page.getByText(/Daily at 08:00 Asia\/Kolkata/)).toBeVisible()

  await page.getByRole('button', { name: /Run now/ }).click()
  await expect(page.getByText(/Working on it/)).toBeVisible()
  await expect(page.getByText('ephemeral')).toBeVisible({ timeout: 12_000 })
})
