import type { SidebarView } from '@/App'

/**
 * URL <-> view mapping for the app shell. Kept dependency-free (History API
 * only): `/` is a new chat, `/c/:id` an open conversation, and each sidebar
 * page has its own path so links, Back/Forward and refresh keep your place.
 */
const VIEW_PATHS: Record<SidebarView, string> = {
  chat: '/',
  projects: '/projects',
  cowork: '/cowork',
  'scheduled-skills': '/scheduled-skills',
  tasks: '/tasks',
  agents: '/agents',
  tools: '/tools',
  connectors: '/connectors',
  skills: '/skills',
  hooks: '/hooks',
  subagents: '/subagents',
}

const PATH_VIEWS = new Map<string, SidebarView>(
  Object.entries(VIEW_PATHS).map(([view, path]) => [path, view as SidebarView]),
)

export interface Route {
  view: SidebarView
  /** Set only for `/c/:id`. */
  conversationId: string | null
}

export function parsePath(pathname: string): Route {
  const path = pathname.replace(/\/+$/, '') || '/'
  const chat = /^\/c\/([^/]+)$/.exec(path)
  if (chat) return { view: 'chat', conversationId: decodeURIComponent(chat[1]) }
  // Unknown paths fall back to a new chat; the app then rewrites the URL to `/`.
  return { view: PATH_VIEWS.get(path) ?? 'chat', conversationId: null }
}

export function pathFor(view: SidebarView, conversationId: string | null): string {
  if (view === 'chat' && conversationId) return `/c/${encodeURIComponent(conversationId)}`
  return VIEW_PATHS[view]
}
