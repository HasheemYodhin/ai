import { useState } from 'react'
import { Plug, RefreshCw, Loader2, Wrench, Plus, Trash2 } from 'lucide-react'
import { useMcpStatus } from '@/hooks/useMcpStatus'
import { ConnectorModal } from './ConnectorModal'
import { apiClient } from '@/api/client'

/** Real MCP server list (connection status + tool counts) — "Connectors" in the sidebar nav. */
export function ConnectorsPage() {
  const { servers, isLoading, error, reload } = useMcpStatus(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [deletingName, setDeletingName] = useState<string | null>(null)

  const handleAdd = async (input: { name: string; command: string; args: string[] }) => {
    await apiClient.addMcpServer(input)
    reload()
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`Remove connector "${name}"? If it's currently connected it'll stay live until the server restarts.`)) return
    setDeletingName(name)
    try {
      await apiClient.deleteMcpServer(name)
      reload()
    } catch (err) {
      alert((err as Error).message)
    } finally {
      setDeletingName(null)
    }
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto scrollbar-thin">
      <header className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border-dark">
        <h1 className="text-sm font-bold text-text-primary dark:text-text-dark-primary flex items-center gap-2">
          <Plug className="w-4 h-4 text-accent" /> Connectors
        </h1>
        <div className="flex items-center gap-1.5">
          <button onClick={reload} className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-tertiary transition-colors" title="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-semibold transition-colors"
          >
            <Plus className="w-3.5 h-3.5" /> Add connector
          </button>
        </div>
      </header>

      <div className="flex-1 p-6">
        <p className="text-xs text-text-secondary dark:text-text-dark-secondary mb-4">
          MCP servers configured on the Dabba server (<code className="font-mono text-[11px]">mcp_servers.json</code>). Connected connectors are available to Web Search, Research, and any Connector/Plugin you pick from the chat "+" menu.
        </p>

        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-text-tertiary">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading connectors…
          </div>
        ) : error ? (
          <div className="p-4 rounded-xl bg-red-500/5 border border-red-500/10 text-sm text-red-500">{error}</div>
        ) : servers.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-text-tertiary">
            <Plug className="w-10 h-10 mb-3 opacity-30" />
            <p className="text-sm font-medium">No connectors configured</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {servers.map(s => (
              <div key={s.name} className="p-4 rounded-2xl border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${s.connected ? 'bg-green-500' : 'bg-gray-400'}`} />
                    <h3 className="text-sm font-semibold text-text-primary dark:text-text-dark-primary">{s.name}</h3>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] text-text-tertiary">{s.connected ? 'connected' : 'disconnected'}</span>
                    <button
                      onClick={() => handleDelete(s.name)}
                      disabled={deletingName === s.name}
                      title="Remove connector"
                      className="p-1 rounded-md hover:bg-surface dark:hover:bg-surface-dark text-text-tertiary hover:text-red-500 transition-colors disabled:opacity-50"
                    >
                      {deletingName === s.name ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                </div>
                <p className="text-[11px] font-mono text-text-tertiary mt-1.5 truncate">{s.command} {s.args?.join(' ')}</p>
                {s.tools?.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2.5">
                    {s.tools.slice(0, 6).map(t => (
                      <span key={t} className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-surface dark:bg-surface-dark text-text-secondary dark:text-text-dark-secondary">
                        <Wrench className="w-2.5 h-2.5" /> {t}
                      </span>
                    ))}
                    {s.tools.length > 6 && (
                      <span className="text-[10px] px-1.5 py-0.5 text-text-tertiary">+{s.tools.length - 6} more</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <ConnectorModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={handleAdd}
      />
    </div>
  )
}
