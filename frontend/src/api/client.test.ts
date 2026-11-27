import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from './client'
import { loadUsageStats } from '@/lib/usageStats'

describe('ApiClient platform contracts', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('stores a server session after login', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      token: 'session-token',
      user: {
        id: 'user_1',
        name: 'Hasheem',
        email: 'hasheem@example.com',
        role: 'member',
        createdAt: 1,
        updatedAt: 1,
      },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const client = new ApiClient('http://dabba.test')
    const result = await client.login('hasheem@example.com', 'long-password')

    expect(result.user.name).toBe('Hasheem')
    expect(localStorage.getItem('dabba-session-token')).toBe('session-token')
  })

  it('reports an unreachable backend clearly during signup', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const client = new ApiClient('')

    await expect(client.signup('New User', 'new@example.com', 'long-password'))
      .rejects.toThrow('Cannot reach the Dabba backend')
  })

  it('turns a Render HTML gateway page into a short usage error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html><body>Bad Gateway</body></html>', {
      status: 502, headers: { 'Content-Type': 'text/html; charset=utf-8' },
    })))
    const client = new ApiClient('http://dabba.test')
    await expect(client.fetchUsage()).rejects.toThrow('Dabba is temporarily unavailable (HTTP 502). Please try again.')
  })

  it('loads complete usage statistics in one request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      conversationCount: 2, messageCount: 8, totalTokens: 50,
      promptTokens: 20, completionTokens: 30, byModel: [],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(loadUsageStats('user_1')).resolves.toMatchObject({
      totalConversations: 2, totalMessages: 8, totalTokens: 50,
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it.each([200, 401])('clears an expired session after a %s restore response', async status => {
    localStorage.setItem('dabba-session-token', 'expired-token')
    const fetchMock = vi.fn().mockResolvedValue(new Response('null', { status }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('http://dabba.test')

    await expect(client.currentUser()).resolves.toBeNull()
    expect(fetchMock).toHaveBeenCalledWith(
      'http://dabba.test/v1/platform/identity/me?restore=true',
      expect.objectContaining({
        cache: 'no-store',
        headers: expect.objectContaining({ Authorization: 'Bearer expired-token' }),
      }),
    )
    expect(localStorage.getItem('dabba-session-token')).toBeNull()
    await expect(client.currentUser()).resolves.toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('requests approval mode for web agent calls', async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"type":"done","content":{}}\n\n'))
        controller.close()
      },
    })
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const client = new ApiClient('http://dabba.test')
    await client.streamAgent('inspect the repo', { onEvent: () => undefined })

    const request = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(request.permission_mode).toBe('ask')
  })

  it('pauses for an approval decision and posts it back to the agent', async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(
          'data: {"type":"approval_required","content":{"call_id":"call-1","name":"file_write","arguments":{"path":"jobs.xlsx"}}}\n\n'
        ))
        controller.enqueue(new TextEncoder().encode('data: {"type":"done","content":{}}\n\n'))
        controller.close()
      },
    })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(body, { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    const onApproval = vi.fn().mockResolvedValue(true)
    const client = new ApiClient('http://dabba.test')
    await client.streamAgent('export jobs', { onApproval, onEvent: () => undefined })

    expect(onApproval).toHaveBeenCalledWith({
      callId: 'call-1',
      name: 'file_write',
      arguments: { path: 'jobs.xlsx' },
    })
    expect(fetchMock.mock.calls[1][0]).toBe('http://dabba.test/v1/agent/approve')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      call_id: 'call-1',
      approved: true,
    })
  })
})
