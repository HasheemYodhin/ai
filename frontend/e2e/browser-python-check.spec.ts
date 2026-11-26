import { expect, test } from '@playwright/test'

test('executes Python in the isolated browser runner', async ({ page }) => {
  test.setTimeout(100_000)
  await page.goto('/')
  const output = await page.evaluate(async () => {
    const modulePath = '/src/lib/browserPython.ts'
    const { runBrowserPython } = await import(modulePath)
    return runBrowserPython("from js import self\nprint(self.origin)\nprint(input().upper())", 'hello', new AbortController().signal)
  })
  expect(output).toMatchObject({ exitCode: 0, stdout: 'null\nHELLO\n', stderr: '', timedOut: false })
  await expect(page.locator('iframe[src="/code-runner.html"]')).toHaveCount(0)
})
