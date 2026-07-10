import { useState, useEffect } from 'react'
import { X, KeyRound, Eye, EyeOff, Loader2 } from 'lucide-react'
import { apiClient } from '@/api/client'
import { providerLabel } from '@/lib/models'

interface ApiKeyPromptModalProps {
  /** Provider id (e.g. "anthropic") of the model that was clicked without a key set. */
  provider: string
  /** Display name of the specific model that triggered this, just for the copy. */
  modelName: string
  onClose: () => void
  /** Called once the key is saved successfully — caller should activate the model and refresh the catalog. */
  onSaved: () => void
}

/**
 * Shown when a user clicks a model with no API key configured yet (instead of
 * that model just sitting disabled with no way to act on it). Saves via the
 * same /v1/agent/keys endpoint the Settings > API Keys tab uses.
 */
export function ApiKeyPromptModal({ provider, modelName, onClose, onSaved }: ApiKeyPromptModalProps) {
  const [key, setKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setKey('')
    setError(null)
  }, [provider])

  const handleSave = async () => {
    const trimmed = key.trim()
    if (!trimmed) return
    setBusy(true)
    setError(null)
    try {
      await apiClient.setProviderKey(provider, trimmed)
      onSaved()
      onClose()
    } catch (err) {
      setError((err as Error).message || 'Failed to save key')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in">
      <div className="fixed inset-0" onClick={onClose} />

      <div className="bg-surface dark:bg-surface-dark-secondary max-w-sm w-full rounded-2xl overflow-hidden relative z-10 border border-border dark:border-border-dark shadow-xl m-4">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border dark:border-border-dark">
          <h3 className="flex items-center gap-2 font-bold text-sm text-text-primary dark:text-text-dark-primary">
            <KeyRound className="w-4 h-4 text-accent" />
            {providerLabel(provider)} API key needed
          </h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-3">
          <p className="text-xs text-text-secondary dark:text-text-dark-secondary">
            <span className="font-medium text-text-primary dark:text-text-dark-primary">{modelName}</span> needs a {providerLabel(provider)} API key.
            Paste one below — it's saved server-side and this model becomes usable immediately.
          </p>

          <div className="relative">
            <input
              autoFocus
              type={showKey ? 'text' : 'password'}
              value={key}
              onChange={e => setKey(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSave()}
              placeholder="Paste API key…"
              className="w-full pl-3.5 pr-10 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors font-mono"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-text-secondary hover:text-text-primary rounded-lg transition-colors"
            >
              {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>

        <div className="px-5 py-4 border-t border-border dark:border-border-dark flex items-center justify-end gap-2 bg-surface-secondary dark:bg-surface-dark-tertiary">
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-xs font-semibold hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={busy || !key.trim()}
            className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-xs font-bold bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors"
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Save & use model
          </button>
        </div>
      </div>
    </div>
  )
}
