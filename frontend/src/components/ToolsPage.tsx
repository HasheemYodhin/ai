import { useState, useMemo } from 'react'
import { Wrench, Search, Loader2 } from 'lucide-react'
import { useMcpStatus } from '@/hooks/useMcpStatus'

/** Flat list of individual MCP tools across all connectors — "Tools" in the sidebar nav. */
export function ToolsPage() {
  const { servers, isLoading } = useMcpStatus(true)
  const [search, setSearch] = useState('')

  const allTools = useMemo(() => {
    const flat = servers.flatMap(s => s.tools.map(tool => ({ server: s.name, tool, connected: s.connected })))
    const q = search.trim().toLowerCase()
    return q ? flat.filter(t => t.tool.toLowerCase().includes(q) || t.server.toLowerCase().includes(q)) : flat
  }, [servers, search])

  return (
    <div className="flex flex-col h-full overflow-y-auto scrollbar-thin">
      <header className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border-dark">
        <h1 className="text-sm font-bold text-text-primary dark:text-text-dark-primary flex items-center gap-2">
          <Wrench className="w-4 h-4 text-accent" /> Tools
        </h1>
      </header>

      <div className="px-6 py-4">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-tertiary" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search tools…"
            className="w-full pl-8 pr-3 py-2 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
          />
        </div>
      </div>

      <div className="flex-1 px-6 pb-6">
        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-text-tertiary">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading tools…
          </div>
        ) : allTools.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-text-tertiary">
            <Wrench className="w-10 h-10 mb-3 opacity-30" />
            <p className="text-sm font-medium">No tools available</p>
            <p className="text-xs mt-1">Connect an MCP server first (see Connectors).</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {allTools.map(({ server, tool, connected }) => (
              <div
                key={`${server}.${tool}`}
                className={`flex items-center justify-between gap-2 p-3 rounded-xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary ${!connected ? 'opacity-45' : ''}`}
              >
                <span className="font-mono text-xs text-text-primary dark:text-text-dark-primary truncate">{tool}</span>
                <span className="text-[10px] text-text-tertiary flex-shrink-0">{server}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
