import { describe, expect, it } from 'vitest'
import { parsePath, pathFor } from '@/lib/routes'

describe('routes', () => {
  it('maps / to a new chat', () => {
    expect(parsePath('/')).toEqual({ view: 'chat', conversationId: null })
  })

  it('maps /c/:id to an open conversation and back', () => {
    expect(parsePath('/c/abc-123')).toEqual({ view: 'chat', conversationId: 'abc-123' })
    expect(pathFor('chat', 'abc-123')).toBe('/c/abc-123')
  })

  it('round-trips every page path, ignoring a trailing slash', () => {
    for (const view of ['projects', 'agents', 'connectors', 'scheduled-skills', 'subagents'] as const) {
      const path = pathFor(view, null)
      expect(parsePath(path).view).toBe(view)
      expect(parsePath(`${path}/`).view).toBe(view)
    }
  })

  it('only gives chats a conversation segment', () => {
    expect(pathFor('agents', 'abc')).toBe('/agents')
  })

  it('falls back to a new chat for unknown paths', () => {
    expect(parsePath('/nope/deeper')).toEqual({ view: 'chat', conversationId: null })
  })

  it('encodes ids safely', () => {
    expect(pathFor('chat', 'a/b')).toBe('/c/a%2Fb')
    expect(parsePath('/c/a%2Fb').conversationId).toBe('a/b')
  })
})
