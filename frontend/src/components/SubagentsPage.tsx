import { useCallback, useEffect, useState } from 'react'
import { Bot, Plus, RefreshCw, Trash2, Wrench } from 'lucide-react'
import { apiClient } from '@/api/client'
import type { AgentDefinition } from '@/types'

export function SubagentsPage() {
  const [definitions, setDefinitions] = useState<AgentDefinition[]>([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [allowedTools, setAllowedTools] = useState('')
  const [model, setModel] = useState('')
  const [effort, setEffort] = useState('')
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')

  const refresh = useCallback(async () => {
    setError('')
    try { setDefinitions(await apiClient.listAgentDefinitions()) }
    catch (err) { setError((err as Error).message) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const create = async () => {
    if (!name.trim() || !systemPrompt.trim()) return
    setBusyId('create'); setError('')
    try {
      const created = await apiClient.createAgentDefinition({
        name: name.trim(), systemPrompt: systemPrompt.trim(), description: description.trim(),
        allowedTools: allowedTools.split(',').map(t => t.trim()).filter(Boolean),
        model: model.trim() || undefined, effort: effort.trim() || undefined,
      })
      setDefinitions(previous => [created, ...previous])
      setName(''); setDescription(''); setSystemPrompt(''); setAllowedTools(''); setModel(''); setEffort('')
    } catch (err) { setError((err as Error).message) }
    finally { setBusyId('') }
  }

  const remove = async (id: string) => {
    try { await apiClient.deleteAgentDefinition(id); setDefinitions(previous => previous.filter(item => item.id !== id)) }
    catch (err) { setError((err as Error).message) }
  }

  return <div className="h-full overflow-y-auto scrollbar-thin">
    <header className="flex items-center justify-between border-b border-border px-6 py-4 dark:border-border-dark">
      <div>
        <h1 className="flex items-center gap-2 text-sm font-bold text-text-primary dark:text-text-dark-primary"><Bot className="h-4 w-4 text-accent" /> Subagent types</h1>
        <p className="mt-1 text-xs text-text-secondary dark:text-text-dark-secondary">
          Named personas with a fixed system prompt, tool allowlist, and model — dispatch prompts to several in parallel via the agent-definitions/dispatch API.
        </p>
      </div>
      <button onClick={() => void refresh()} className="rounded-lg p-2 text-text-secondary hover:bg-surface-secondary dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary"><RefreshCw className="h-4 w-4" /></button>
    </header>

    <div className="grid gap-5 p-6 lg:grid-cols-[380px_1fr]">
      <section className="h-fit rounded-2xl border border-border bg-surface-secondary p-4 dark:border-border-dark dark:bg-surface-dark-secondary">
        <h2 className="mb-3 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Create subagent type</h2>
        <div className="space-y-3">
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Name (e.g. Reviewer)" className="glass-input w-full rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
          <input value={description} onChange={e => setDescription(e.target.value)} placeholder="Short description" className="glass-input w-full rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
          <textarea value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)} placeholder="System prompt — defines this persona's behavior" rows={5} className="glass-input w-full resize-none rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
          <input value={allowedTools} onChange={e => setAllowedTools(e.target.value)} placeholder="Allowed tools, comma-separated — blank = unrestricted" className="glass-input w-full rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
          <div className="grid grid-cols-2 gap-2">
            <input value={model} onChange={e => setModel(e.target.value)} placeholder="Model (optional)" className="glass-input rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
            <input value={effort} onChange={e => setEffort(e.target.value)} placeholder="Effort (optional)" className="glass-input rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
          </div>
          <button disabled={!name.trim() || !systemPrompt.trim() || busyId === 'create'} onClick={() => void create()} className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"><Plus className="h-3.5 w-3.5" /> Create subagent type</button>
          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Subagent types ({definitions.length})</h2>
        <div className="space-y-2">
          {definitions.map(def => (
            <article key={def.id} className="rounded-xl border border-border bg-surface-secondary p-3 dark:border-border-dark dark:bg-surface-dark-secondary">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-xs font-semibold text-text-primary dark:text-text-dark-primary">{def.name}</h3>
                  {def.description && <p className="mt-0.5 text-[11px] text-text-secondary dark:text-text-dark-secondary">{def.description}</p>}
                  <p className="mt-1 line-clamp-2 text-[10px] text-text-tertiary">{def.systemPrompt}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px] text-text-tertiary">
                    <span className="flex items-center gap-1"><Wrench className="h-3 w-3" />{def.allowedTools.length ? def.allowedTools.join(', ') : 'All tools'}</span>
                    {def.model && <span className="rounded-full bg-surface-tertiary px-1.5 py-0.5 dark:bg-surface-dark-tertiary">{def.model}</span>}
                    {def.effort && <span className="rounded-full bg-surface-tertiary px-1.5 py-0.5 dark:bg-surface-dark-tertiary">{def.effort}</span>}
                  </div>
                </div>
                <button onClick={() => void remove(def.id)} className="flex-shrink-0 p-1 text-text-tertiary hover:text-red-500"><Trash2 className="h-3.5 w-3.5" /></button>
              </div>
            </article>
          ))}
          {!definitions.length && <div className="rounded-xl border border-dashed border-border p-10 text-center text-xs text-text-tertiary dark:border-border-dark">No subagent types yet.</div>}
        </div>
      </section>
    </div>
  </div>
}
