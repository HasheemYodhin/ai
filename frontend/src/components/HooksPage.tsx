import { useCallback, useEffect, useState } from 'react'
import { Webhook, Plus, RefreshCw, Trash2, ShieldBan, CheckCircle2, XCircle } from 'lucide-react'
import { apiClient } from '@/api/client'
import type { AgentHook, HookEvent, HookRun } from '@/types'

const EVENT_LABELS: Record<HookEvent, string> = {
  session_start: 'Session start',
  session_end: 'Session end',
  user_prompt_submit: 'User prompt submitted',
  pre_tool_call: 'Before a tool call (can block it)',
  post_tool_call: 'After a tool call',
}

export function HooksPage() {
  const [hooks, setHooks] = useState<AgentHook[]>([])
  const [events, setEvents] = useState<HookEvent[]>([])
  const [runs, setRuns] = useState<HookRun[]>([])
  const [event, setEvent] = useState<HookEvent>('pre_tool_call')
  const [matcher, setMatcher] = useState('')
  const [command, setCommand] = useState('')
  const [timeout, setTimeoutValue] = useState(30)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')

  const refresh = useCallback(async () => {
    setError('')
    try {
      const [list, runList] = await Promise.all([apiClient.listHooks(), apiClient.listHookRuns()])
      setHooks(list.hooks)
      setEvents(list.events.length ? list.events : Object.keys(EVENT_LABELS) as HookEvent[])
      setRuns(runList.slice().reverse())
    } catch (err) { setError((err as Error).message) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const create = async () => {
    if (!command.trim()) return
    setBusyId('create'); setError('')
    try {
      const created = await apiClient.createHook({ event, command: command.trim(), matcher: matcher.trim(), timeout, enabled: true })
      setHooks(previous => [created, ...previous])
      setCommand(''); setMatcher('')
    } catch (err) { setError((err as Error).message) }
    finally { setBusyId('') }
  }

  const toggle = async (hook: AgentHook) => {
    try {
      const saved = await apiClient.updateHook(hook.id, { enabled: !hook.enabled })
      setHooks(previous => previous.map(item => item.id === saved.id ? saved : item))
    } catch (err) { setError((err as Error).message) }
  }

  const remove = async (id: string) => {
    try { await apiClient.deleteHook(id); setHooks(previous => previous.filter(item => item.id !== id)) }
    catch (err) { setError((err as Error).message) }
  }

  return <div className="h-full overflow-y-auto scrollbar-thin">
    <header className="flex items-center justify-between border-b border-border px-6 py-4 dark:border-border-dark">
      <div>
        <h1 className="flex items-center gap-2 text-sm font-bold text-text-primary dark:text-text-dark-primary"><Webhook className="h-4 w-4 text-accent" /> Hooks</h1>
        <p className="mt-1 text-xs text-text-secondary dark:text-text-dark-secondary">
          Run a shell command automatically on agent events. A "Before a tool call" hook that exits non-zero blocks that tool call.
        </p>
      </div>
      <button onClick={() => void refresh()} className="rounded-lg p-2 text-text-secondary hover:bg-surface-secondary dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary"><RefreshCw className="h-4 w-4" /></button>
    </header>

    <div className="grid gap-5 p-6 lg:grid-cols-[360px_1fr]">
      <section className="h-fit rounded-2xl border border-border bg-surface-secondary p-4 dark:border-border-dark dark:bg-surface-dark-secondary">
        <h2 className="mb-3 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Add hook</h2>
        <div className="space-y-3">
          <select value={event} onChange={e => setEvent(e.target.value as HookEvent)} className="glass-input w-full rounded-lg px-3 py-2 text-xs text-text-primary dark:text-text-dark-primary">
            {events.map(ev => <option key={ev} value={ev}>{EVENT_LABELS[ev] ?? ev}</option>)}
          </select>
          {(event === 'pre_tool_call' || event === 'post_tool_call') && (
            <input value={matcher} onChange={e => setMatcher(e.target.value)} placeholder="Tool name(s), comma-separated — blank matches every tool" className="glass-input w-full rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
          )}
          <textarea value={command} onChange={e => setCommand(e.target.value)} placeholder="Shell command to run — reads the event as JSON on stdin and $DABBA_HOOK_CONTEXT" rows={4} className="glass-input w-full resize-none rounded-lg px-3 py-2 text-xs font-mono text-text-primary outline-none dark:text-text-dark-primary" />
          <div className="flex items-center gap-2">
            <label className="text-[10px] text-text-tertiary">Timeout (s)</label>
            <input type="number" min={1} value={timeout} onChange={e => setTimeoutValue(Number(e.target.value))} className="glass-input w-20 rounded-lg px-3 py-2 text-xs text-text-primary dark:text-text-dark-primary" />
          </div>
          <button disabled={!command.trim() || busyId === 'create'} onClick={() => void create()} className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"><Plus className="h-3.5 w-3.5" /> Add hook</button>
          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>
      </section>

      <div className="space-y-5">
        <section>
          <h2 className="mb-2 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Configured hooks ({hooks.length})</h2>
          <div className="space-y-2">
            {hooks.map(hook => <article key={hook.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface-secondary p-3 dark:border-border-dark dark:bg-surface-dark-secondary">
              <button onClick={() => void toggle(hook)} className={`h-5 w-9 flex-shrink-0 rounded-full p-0.5 transition-colors ${hook.enabled ? 'bg-accent' : 'bg-surface-tertiary dark:bg-surface-dark-tertiary'}`} title={hook.enabled ? 'Disable' : 'Enable'}><span className={`block h-4 w-4 rounded-full bg-white transition-transform ${hook.enabled ? 'translate-x-4' : ''}`} /></button>
              <div className="min-w-0 flex-1">
                <h3 className="flex items-center gap-1.5 truncate text-xs font-semibold text-text-primary dark:text-text-dark-primary">
                  {EVENT_LABELS[hook.event] ?? hook.event}
                  {hook.matcher && <code className="rounded bg-surface-tertiary px-1.5 py-0.5 text-[10px] font-normal dark:bg-surface-dark-tertiary">{hook.matcher}</code>}
                </h3>
                <p className="mt-0.5 truncate font-mono text-[10px] text-text-tertiary">{hook.command}</p>
              </div>
              <button onClick={() => void remove(hook.id)} className="p-1.5 text-text-tertiary hover:text-red-500"><Trash2 className="h-3.5 w-3.5" /></button>
            </article>)}
            {!hooks.length && <div className="rounded-xl border border-dashed border-border p-10 text-center text-xs text-text-tertiary dark:border-border-dark">No hooks configured yet.</div>}
          </div>
        </section>
        <section>
          <h2 className="mb-2 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Recent runs</h2>
          <div className="overflow-hidden rounded-xl border border-border dark:border-border-dark">
            {runs.slice(0, 20).map((run, i) => <div key={`${run.hook_id}-${run.timestamp}-${i}`} className="flex items-center gap-3 border-b border-border px-3 py-2.5 last:border-0 dark:border-border-dark">
              {run.blocked
                ? <ShieldBan className="h-3.5 w-3.5 flex-shrink-0 text-red-500" />
                : run.error
                  ? <XCircle className="h-3.5 w-3.5 flex-shrink-0 text-amber-500" />
                  : <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0 text-green-500" />}
              <span className="flex-1 truncate text-[11px] text-text-secondary dark:text-text-dark-secondary">
                {EVENT_LABELS[run.event] ?? run.event}{run.tool ? ` · ${run.tool}` : ''}
                {run.blocked && ' — blocked'}
                {run.error && ` — ${run.error}`}
              </span>
              <span className="text-[10px] text-text-tertiary">{new Date(run.timestamp * 1000).toLocaleString()}</span>
            </div>)}
            {!runs.length && <p className="p-5 text-center text-[11px] text-text-tertiary">Hook run history will appear here.</p>}
          </div>
        </section>
      </div>
    </div>
  </div>
}
