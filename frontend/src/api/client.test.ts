import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from './client'

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
