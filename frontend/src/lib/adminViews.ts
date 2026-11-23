import type { SidebarView } from '@/App'

/**
 * Views whose backend endpoints are admin-only (see the admin_only check in
 * dabba/api/server.py). Regular users see a lock in the sidebar and an
 * explanation instead of the page.
 */
export const ADMIN_ONLY_VIEWS: ReadonlySet<SidebarView> = new Set<SidebarView>([
  'cowork',        // /v1/platform/cowork/
  'scheduled-skills', // /v1/platform/scheduled-skills
  'tools',         // /v1/mcp/
  'connectors',    // /v1/mcp/
  'hooks',         // /v1/hooks
  'subagents',     // /v1/platform/agent-definitions
])

export const ADMIN_VIEW_LABELS: Partial<Record<SidebarView, string>> = {
  cowork: 'Cowork',
  'scheduled-skills': 'Scheduled skills',
  tools: 'Tools',
  connectors: 'Connectors',
  hooks: 'Hooks',
  subagents: 'Subagent types',
}
