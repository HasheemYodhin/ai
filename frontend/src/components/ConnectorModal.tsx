import { useState, useEffect } from 'react'
import { X, Plug, Loader2 } from 'lucide-react'

interface ConnectorModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (input: { name: string; command: string; args: string[] }) => Promise<void>
}

/**
 * "Add connector" — writes a new stdio MCP server to mcp_servers.json and
 * connects it immediately (no server restart needed). Same shape as
 * Claude Desktop's mcpServers config: a command + args to launch it.
 */
export function ConnectorModal({ isOpen, onClose, onSubmit }: ConnectorModalProps) {
  const [name, setName] = useState('')
  const [command, setCommand] = useState('')
  const [args, setArgs] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setName('')
      setCommand('')
      setArgs('')
      setError(null)
    }
  }, [isOpen])

  if (!isOpen) return null

  const canSubmit = name.trim() && command.trim() && !busy

  const handleSubmit = async () => {
    if (!canSubmit) return
    setBusy(true)
    setError(null)
    try {
      // Splits on whitespace but keeps "quoted strings" together — same
      // convention as a shell command line, since args launch a real process.
      const parsedArgs = args.match(/"[^"]*"|'[^']*'|\S+/g)?.map(a => a.replace(/^['"]|['"]$/g, '')) ?? []
      await onSubmit({ name: name.trim(), command: command.trim(), args: parsedArgs })
      onClose()
    } catch (err) {
      setError((err as Error).message || 'Failed to add connector')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in">
      <div className="fixed inset-0" onClick={onClose} />

      <div className="bg-surface dark:bg-surface-dark-secondary max-w-md w-full rounded-2xl overflow-hidden relative z-10 border border-border dark:border-border-dark shadow-xl m-4">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border dark:border-border-dark">
          <h3 className="flex items-center gap-2 font-bold text-sm text-text-primary dark:text-text-dark-primary">
            <Plug className="w-4 h-4 text-accent" />
            Add connector
          </h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <p className="text-xs text-text-secondary dark:text-text-dark-secondary">
            Adds a stdio MCP server — the same config shape Claude Desktop uses. It connects immediately, no server restart needed.
          </p>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Name</label>
            <input
              autoFocus
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. filesystem"
              className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors font-mono"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Command</label>
            <input
              value={command}
              onChange={e => setCommand(e.target.value)}
              placeholder="e.g. npx"
              className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors font-mono"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Args <span className="text-text-tertiary font-normal">(space-separated)</span></label>
            <input
              value={args}
              onChange={e => setArgs(e.target.value)}
              placeholder='-y @modelcontextprotocol/server-filesystem /path'
              className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors font-mono"
            />
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>

        <div className="px-5 py-4 border-t border-border dark:border-border-dark flex items-center justify-end gap-2 bg-surface-secondary dark:bg-surface-dark-tertiary">
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-xs font-semibold hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-xs font-bold bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors"
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Add & connect
          </button>
        </div>
      </div>
    </div>
  )
}
