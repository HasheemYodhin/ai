import { expect, test } from '@playwright/test'

const javaSnippet = 'public final class ReverseString { public static void main(String[] args) { System.out.println(new StringBuilder("Dabba").reverse()); } }'

for (const available of [false, true]) {
  test(available ? 'Java uses the local runner when the JDK is available' : 'Locked Java offers a download and browser playground', async ({ page }) => {
    const messages = [
      { id: 'prompt', role: 'user', content: 'Reverse a string in Java', timestamp: 1 },
      { id: 'reply', role: 'assistant', content: ['```java', javaSnippet, '```'].join('\n'), timestamp: 2 },
    ]
    const conversation = { id: 'java', title: 'Reverse a string', messages, createdAt: 1, updatedAt: 2, revision: 1 }
    await page.addInitScript(() => localStorage.setItem('dabba-session-token', 'java-test'))
    await page.route('**/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/identity/me')) return route.fulfill({ json: { id: 'u1', name: 'Tester', email: 'user@example.com', role: 'admin', createdAt: 1, updatedAt: 1 } })
      if (path === '/v1/conversations') return route.fulfill({ json: { conversations: [conversation] } })
      if (path === '/v1/conversations/java') return route.fulfill({ json: conversation })
      if (path === '/v1/code/languages') return route.fulfill({ json: { unavailableReason: null, languages: [{ id: 'java', available }] } })
      if (path === '/v1/code/execute') {
        expect(route.request().postDataJSON()).toMatchObject({ language: 'java', code: javaSnippet })
        return route.fulfill({ json: { language: 'java', exitCode: 0, stdout: 'abbaD\n', stderr: '', timedOut: false, durationMs: 42 } })
      }
      return route.fulfill({ json: [] })
    })

    await page.goto('/c/java')
    if (available) {
      await page.getByRole('button', { name: 'Run', exact: true }).click()
      await expect(page.getByText('abbaD', { exact: true })).toBeVisible()
    } else {
      await page.getByRole('button', { name: /Java JDK is missing/ }).click()
      await expect(page.getByRole('link', { name: 'Open Java playground' })).toHaveAttribute('href', 'https://javafiddle.leaningtech.com/')
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.getByRole('button', { name: 'Download Java source' }).click(),
      ])
      expect(download.suggestedFilename()).toBe('ReverseString.java')
    }
  })
}
