import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/client'
import { useProcessNotifications } from '@/hooks/useRunNotifications'

describe('useProcessNotifications', () => {
  afterEach(() => vi.restoreAllMocks())

  it('notifies once a running process transitions to a terminal state', async () => {
    let call = 0
    vi.spyOn(apiClient, 'listBackgroundProcesses').mockImplementation(async () => {
      call += 1
      const status = call === 1 ? 'running' : 'exited'
      return [{ process_id: 'p1', command: 'npm run dev', pid: 1, status, uptime_seconds: call }]
    })

    const { result } = renderHook(() => useProcessNotifications(10))

    // First poll just observes it running — no notice yet.
    await waitFor(() => expect(call).toBeGreaterThanOrEqual(1))
    expect(result.current.notices).toHaveLength(0)

    // A later poll sees the transition to "exited" — fires a notice exactly once.
    await waitFor(() => expect(result.current.notices).toHaveLength(1))
    expect(result.current.notices[0].message).toContain('npm run dev')
    expect(result.current.notices[0].tone).toBe('success')

    act(() => result.current.dismiss(result.current.notices[0].id))
    expect(result.current.notices).toHaveLength(0)
  })

  it('does not notify for a process seen for the first time already finished', async () => {
    vi.spyOn(apiClient, 'listBackgroundProcesses')
      .mockResolvedValue([{ process_id: 'p2', command: 'old build', pid: 2, status: 'exited', uptime_seconds: 100 }])

    const { result } = renderHook(() => useProcessNotifications(10))
    await waitFor(() => expect(apiClient.listBackgroundProcesses).toHaveBeenCalled())
    expect(result.current.notices).toHaveLength(0)
  })

  it('swallows a transient fetch error instead of throwing', async () => {
    vi.spyOn(apiClient, 'listBackgroundProcesses').mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useProcessNotifications(10))
    await waitFor(() => expect(apiClient.listBackgroundProcesses).toHaveBeenCalled())
    expect(result.current.notices).toHaveLength(0)
  })
})
