import { useCallback, useEffect, useMemo, useState } from 'react'
import { Ban, Bot, BriefcaseBusiness, CalendarClock, CheckSquare, ChevronRight, Clock3, FolderOpen, Play, Plus, RefreshCw, ShieldCheck, Square, Trash2, Users, Wrench, X } from 'lucide-react'
import { apiClient } from '@/api/client'
import type { CoworkItem, CoworkPriority, CoworkRun, CoworkStatus, CoworkSubtask, CoworkSchedule } from '@/types'
import { cn } from '@/lib/utils'
import { useSettings } from '@/hooks/useSettings'
import { FolderPicker } from './FolderPicker'

const COLUMNS: Array<{ status: CoworkStatus; label: string }> = [
  { status: 'inbox', label: 'Inbox' }, { status: 'planned', label: 'Planned' },
  { status: 'in_progress', label: 'In progress' }, { status: 'blocked', label: 'Blocked' },
  { status: 'done', label: 'Done' },
]
const priorityTone: Record<CoworkPriority, string> = {
  low: 'bg-slate-500/10 text-slate-500', medium: 'bg-blue-500/10 text-blue-500',
  high: 'bg-amber-500/10 text-amber-600', urgent: 'bg-red-500/10 text-red-500',
}

export function CoworkPage() {
  const { settings } = useSettings()
  const [items, setItems] = useState<CoworkItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [runs, setRuns] = useState<CoworkRun[]>([])
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState<CoworkPriority>('medium')
  const [assignToDabba, setAssignToDabba] = useState(true)
  const [allowTools, setAllowTools] = useState(false)
  const [workspacePath, setWorkspacePath] = useState('')
  const [folderPickerOpen, setFolderPickerOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [subtasks, setSubtasks] = useState<CoworkSubtask[]>([])
  const [newSubtask, setNewSubtask] = useState('')
  const [schedules, setSchedules] = useState<CoworkSchedule[]>([])
  const [schedCadence, setSchedCadence] = useState<'interval' | 'daily' | 'weekly'>('daily')
  const [schedTime, setSchedTime] = useState('09:00')
  const [schedInterval, setSchedInterval] = useState(60)

  const selected = items.find(item => item.id === selectedId) ?? null
  const activeRun = runs.find(run => ['queued', 'running'].includes(run.status)) ?? null

  const refresh = useCallback(async () => {
    setError('')
    try { setItems(await apiClient.listCoworkItems()) }
    catch (err) { setError((err as Error).message) }
  }, [])
  const refreshRuns = useCallback(async (itemId: string) => {
    try { setRuns(await apiClient.listCoworkRuns(itemId)) }
    catch (err) { setError((err as Error).message) }
  }, [])

  const refreshSubtasks = useCallback(async (itemId: string) => {
    try { setSubtasks(await apiClient.listCoworkSubtasks(itemId)) }
    catch (err) { setError((err as Error).message) }
  }, [])
  const refreshSchedules = useCallback(async (itemId: string) => {
    try { setSchedules(await apiClient.listCoworkSchedules(itemId)) }
    catch (err) { setError((err as Error).message) }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!selectedId) { setRuns([]); setSubtasks([]); setSchedules([]); return }
    void refreshRuns(selectedId)
    void refreshSubtasks(selectedId)
    void refreshSchedules(selectedId)
    const timer = window.setInterval(() => { void refreshRuns(selectedId); void refresh() }, 2500)
    return () => window.clearInterval(timer)
  }, [refresh, refreshRuns, refreshSubtasks, refreshSchedules, selectedId])

  const addSchedule = async () => {
    if (!selectedId) return
    try {
      const created = await apiClient.createCoworkSchedule(selectedId, {
        cadence: schedCadence,
        ...(schedCadence === 'interval' ? { intervalMinutes: schedInterval } : { timeOfDay: schedTime }),
        ...(schedCadence === 'weekly' ? { weekdays: [1] } : {}),
        mode: 'agent',
        ...(workspacePath.trim() ? { workspacePath: workspacePath.trim() } : {}),
        model: settings.model, effort: settings.effort,
      })
      setSchedules(previous => [created, ...previous])
    } catch (err) { setError((err as Error).message) }
  }
  const toggleSchedule = async (sched: CoworkSchedule) => {
    setSchedules(previous => previous.map(s => s.id === sched.id ? { ...s, enabled: !s.enabled } : s))
    try { await apiClient.updateCoworkSchedule(sched.id, { enabled: !sched.enabled }) }
    catch (err) { setError((err as Error).message); if (selectedId) void refreshSchedules(selectedId) }
  }
  const removeSchedule = async (sched: CoworkSchedule) => {
    setSchedules(previous => previous.filter(s => s.id !== sched.id))
    try { await apiClient.deleteCoworkSchedule(sched.id) }
    catch (err) { setError((err as Error).message) }
  }
  const scheduleLabel = (s: CoworkSchedule) =>
    s.cadence === 'interval' ? `Every ${s.intervalMinutes} min`
      : s.cadence === 'daily' ? `Daily at ${s.timeOfDay}`
        : `Weekly at ${s.timeOfDay}`

  const addSubtask = async () => {
    const title = newSubtask.trim()
    if (!title || !selectedId) return
    setNewSubtask('')
    try {
      const created = await apiClient.addCoworkSubtask(selectedId, title)
      setSubtasks(previous => [...previous, created])
    } catch (err) { setError((err as Error).message) }
  }
  const toggleSubtask = async (sub: CoworkSubtask) => {
    const next = sub.status === 'done' ? 'pending' : 'done'
    setSubtasks(previous => previous.map(s => s.id === sub.id ? { ...s, status: next } : s))
    try { await apiClient.updateCoworkSubtask(sub.id, { status: next }) }
    catch (err) { setError((err as Error).message); if (selectedId) void refreshSubtasks(selectedId) }
  }
  const removeSubtask = async (sub: CoworkSubtask) => {
    setSubtasks(previous => previous.filter(s => s.id !== sub.id))
    try { await apiClient.deleteCoworkSubtask(sub.id) }
    catch (err) { setError((err as Error).message) }
  }

  const counts = useMemo(() => Object.fromEntries(COLUMNS.map(column => [
    column.status, items.filter(item => item.status === column.status).length,
  ])), [items])

  const startRun = async (item: CoworkItem, mode: 'safe' | 'agent', path = '') => {
    setBusy(true); setError('')
    try {
      const run = await apiClient.runCoworkItem(item.id, {
        mode, model: settings.model, effort: settings.effort,
        ...(mode === 'agent' && path.trim() ? { workspacePath: path.trim() } : {}),
      })
      setRuns(previous => [run, ...previous]); setSelectedId(item.id); await refresh()
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  const create = async () => {
    if (!title.trim() || busy) return
    setBusy(true); setError('')
    try {
      const item = await apiClient.createCoworkItem({
        title: title.trim(), description: description.trim(), priority,
        status: assignToDabba ? 'planned' : 'inbox', assignee: assignToDabba ? 'Dabba' : null,
      })
      setItems(previous => [item, ...previous]); setSelectedId(item.id)
      setTitle(''); setDescription('')
      if (assignToDabba) {
        const run = await apiClient.runCoworkItem(item.id, {
          mode: allowTools ? 'agent' : 'safe',
          model: settings.model,
          effort: settings.effort,
          ...(allowTools && workspacePath.trim() ? { workspacePath: workspacePath.trim() } : {}),
        })
        setRuns([run]); await refresh()
      }
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  const update = async (id: string, changes: Partial<CoworkItem>) => {
    const before = items
    setItems(previous => previous.map(item => item.id === id ? { ...item, ...changes } : item))
    try {
      const saved = await apiClient.updateCoworkItem(id, changes)
      setItems(previous => previous.map(item => item.id === id ? saved : item))
    } catch (err) { setItems(before); setError((err as Error).message) }
  }
  const remove = async (id: string) => {
    try { await apiClient.deleteCoworkItem(id); setItems(previous => previous.filter(item => item.id !== id)); if (selectedId === id) setSelectedId(null) }
    catch (err) { setError((err as Error).message) }
  }
  const cancel = async (run: CoworkRun) => {
    try { const saved = await apiClient.cancelCoworkRun(run.id); setRuns(previous => previous.map(item => item.id === saved.id ? saved : item)); await refresh() }
    catch (err) { setError((err as Error).message) }
  }

  return <div className="flex h-full flex-col overflow-hidden">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-4 dark:border-border-dark">
      <div><h1 className="flex items-center gap-2 text-sm font-semibold text-text-primary dark:text-text-dark-primary"><BriefcaseBusiness className="h-4 w-4 text-accent" /> Cowork</h1><p className="mt-1 text-xs text-text-secondary dark:text-text-dark-secondary">Give Dabba an assignment, let it work with tools and connectors, and inspect the result.</p></div>
      <button onClick={() => void refresh()} className="rounded-lg p-2 text-text-secondary hover:bg-surface-secondary dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary" aria-label="Refresh" title="Refresh"><RefreshCw className="h-4 w-4" /></button>
    </header>

    <div className="border-b border-border px-6 py-3 dark:border-border-dark">
      <div className="grid max-w-4xl gap-2 sm:grid-cols-[1fr_140px_auto]">
        <input value={title} onChange={event => setTitle(event.target.value)} placeholder="What should Cowork accomplish?" className="glass-input min-w-0 rounded-lg px-3 py-2 text-sm text-text-primary outline-none dark:text-text-dark-primary" />
        <select value={priority} onChange={event => setPriority(event.target.value as CoworkPriority)} className="glass-input rounded-lg px-2 text-xs text-text-primary dark:text-text-dark-primary"><option value="low">Low priority</option><option value="medium">Medium priority</option><option value="high">High priority</option><option value="urgent">Urgent</option></select>
        <button disabled={!title.trim() || busy} onClick={() => void create()} className="flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"><Plus className="h-3.5 w-3.5" /> {assignToDabba ? 'Create & run' : 'Add'}</button>
      </div>
      <textarea value={description} onChange={event => setDescription(event.target.value)} placeholder="Instructions, expected output, constraints…" rows={2} className="glass-input mt-2 w-full max-w-4xl resize-none rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
      <div className="mt-2 flex max-w-4xl flex-wrap items-center gap-4 text-[11px] text-text-secondary dark:text-text-dark-secondary">
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={assignToDabba} onChange={event => setAssignToDabba(event.target.checked)} className="accent-accent" /> Assign to Dabba</label>
        {assignToDabba && <label className="flex items-center gap-1.5"><input type="checkbox" checked={allowTools} onChange={event => setAllowTools(event.target.checked)} className="accent-accent" /> Allow tools and connected apps</label>}
        {assignToDabba && allowTools && <button onClick={() => setFolderPickerOpen(true)} className="glass-input flex min-w-[230px] flex-1 items-center gap-2 rounded-md px-2 py-1 text-left text-[11px] text-text-primary dark:text-text-dark-primary"><FolderOpen className="h-3.5 w-3.5 flex-shrink-0 text-accent" /><span className="truncate">{workspacePath || 'Choose working folder…'}</span></button>}
      </div>
      {allowTools && assignToDabba && <p className="mt-1.5 text-xs text-amber-600">Tool mode can read connected apps and modify files in the selected workspace. Start it only for assignments you trust.</p>}
      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
    </div>

    <div className="flex-1 overflow-x-auto overflow-y-hidden p-4">
      <div className="grid h-full min-w-[1040px] grid-cols-5 gap-3">
        {COLUMNS.map(column => <section key={column.status} className="flex min-h-0 flex-col rounded-2xl bg-surface-secondary/70 p-2 dark:bg-surface-dark-secondary">
          <div className="mb-2 flex items-center justify-between px-1.5 py-1"><h2 className="text-xs font-semibold text-text-primary dark:text-text-dark-primary">{column.label}</h2><span className="rounded-full bg-surface-tertiary px-2 py-0.5 text-xs text-text-tertiary dark:bg-surface-dark-tertiary">{counts[column.status] ?? 0}</span></div>
          <div className="space-y-2 overflow-y-auto scrollbar-thin">
            {items.filter(item => item.status === column.status).map(item => <article key={item.id} className="rounded-xl border border-border bg-surface p-3 dark:border-border-dark dark:bg-surface-dark-tertiary">
              <div className="flex items-start gap-2"><button onClick={() => setSelectedId(item.id)} className="min-w-0 flex-1 text-left text-xs font-semibold text-text-primary hover:text-accent dark:text-text-dark-primary">{item.title}</button><button disabled={item.status === 'in_progress'} onClick={() => void remove(item.id)} className="text-text-tertiary hover:text-red-500 disabled:opacity-30" aria-label="Delete" title="Delete"><Trash2 className="h-3.5 w-3.5" /></button></div>
              {item.description && <p className="mt-1 line-clamp-2 text-[11px] text-text-secondary dark:text-text-dark-secondary">{item.description}</p>}
              <div className="mt-3 flex items-center justify-between gap-2"><span className={cn('rounded-full px-2 py-0.5 text-xs font-semibold uppercase', priorityTone[item.priority])}>{item.priority}</span>{item.assignee && <span className="flex min-w-0 items-center gap-1 truncate text-xs text-text-tertiary"><Users className="h-3 w-3" />{item.assignee}</span>}</div>
              {item.status === 'in_progress' ? <button onClick={() => setSelectedId(item.id)} className="mt-2 flex w-full items-center justify-center gap-1 rounded-md bg-accent/10 px-2 py-1.5 text-xs font-semibold text-accent"><span className="h-2 w-2 animate-pulse rounded-full bg-accent" /> Dabba is working</button> : <div className="mt-2 flex gap-1"><button disabled={busy} onClick={() => void startRun(item, 'safe')} className="flex flex-1 items-center justify-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-semibold text-text-secondary hover:text-accent dark:border-border-dark dark:text-text-dark-secondary"><Play className="h-3 w-3" /> Run</button><button onClick={() => setSelectedId(item.id)} className="rounded-md border border-border p-1 text-text-tertiary hover:text-accent dark:border-border-dark" aria-label="Open details" title="Open details"><ChevronRight className="h-3.5 w-3.5" /></button></div>}
              <select value={item.status} disabled={item.status === 'in_progress'} onChange={event => void update(item.id, { status: event.target.value as CoworkStatus })} className="glass-input mt-2 w-full rounded-md px-2 py-1 text-xs text-text-secondary disabled:opacity-50 dark:text-text-dark-secondary">{COLUMNS.map(option => <option key={option.status} value={option.status}>{option.label}</option>)}</select>
            </article>)}
            {!counts[column.status] && <div className="rounded-xl border border-dashed border-border p-5 text-center text-[11px] text-text-tertiary dark:border-border-dark">No work here</div>}
          </div>
        </section>)}
      </div>
    </div>

    {selected && <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onMouseDown={event => { if (event.target === event.currentTarget) setSelectedId(null) }}>
      <aside className="flex h-full w-full max-w-xl flex-col border-l border-border bg-surface shadow-2xl dark:border-border-dark dark:bg-surface-dark">
        <div className="flex items-start gap-3 border-b border-border p-5 dark:border-border-dark"><div className="min-w-0 flex-1"><p className="text-xs font-semibold text-accent">Cowork assignment</p><h2 className="mt-1 text-base font-semibold text-text-primary dark:text-text-dark-primary">{selected.title}</h2><p className="mt-2 whitespace-pre-wrap text-xs text-text-secondary dark:text-text-dark-secondary">{selected.description || 'No additional instructions.'}</p></div><button aria-label="Close task details" onClick={() => setSelectedId(null)} className="p-1 text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary"><X className="h-4 w-4" /></button></div>
        <div className="border-b border-border p-4 dark:border-border-dark"><div className="flex flex-wrap gap-2"><button disabled={!!activeRun || busy} onClick={() => void startRun(selected, 'safe')} className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"><ShieldCheck className="h-3.5 w-3.5" /> Run safely</button><button disabled={!!activeRun || busy} onClick={() => void startRun(selected, 'agent', workspacePath)} className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-text-primary hover:border-accent hover:text-accent disabled:opacity-40 dark:border-border-dark dark:text-text-dark-primary"><Wrench className="h-3.5 w-3.5" /> Run with tools</button>{activeRun && <button onClick={() => void cancel(activeRun)} className="flex items-center gap-1.5 rounded-lg bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-500"><Ban className="h-3.5 w-3.5" /> Cancel</button>}</div><button onClick={() => setFolderPickerOpen(true)} className="glass-input mt-2 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-text-primary dark:text-text-dark-primary"><FolderOpen className="h-4 w-4 flex-shrink-0 text-accent" /><span className="truncate">{workspacePath || 'Choose working folder for tool runs…'}</span></button></div>
        <div className="border-b border-border p-4 dark:border-border-dark">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="flex items-center gap-1.5 text-xs font-semibold text-text-primary dark:text-text-dark-primary"><CheckSquare className="h-3.5 w-3.5 text-accent" /> Checklist{subtasks.length > 0 && <span className="text-xs font-normal text-text-tertiary">{subtasks.filter(s => s.status === 'done').length}/{subtasks.length}</span>}</h3>
          </div>
          <div className="space-y-1">
            {subtasks.map(sub => (
              <div key={sub.id} className="group flex items-center gap-2">
                <button onClick={() => void toggleSubtask(sub)} className="flex-shrink-0 text-text-tertiary hover:text-accent">
                  {sub.status === 'done' ? <CheckSquare className="h-4 w-4 text-accent" /> : <Square className="h-4 w-4" />}
                </button>
                <span className={cn('flex-1 text-xs', sub.status === 'done' ? 'text-text-tertiary line-through' : 'text-text-secondary dark:text-text-dark-secondary')}>{sub.title}</span>
                <button aria-label="Remove subtask" onClick={() => void removeSubtask(sub)} className="flex-shrink-0 text-text-tertiary opacity-0 hover:text-red-500 group-hover:opacity-100"><X className="h-3 w-3" /></button>
              </div>
            ))}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <input value={newSubtask} onChange={e => setNewSubtask(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); void addSubtask() } }} placeholder="Add a checklist item…" className="glass-input flex-1 rounded-lg px-2.5 py-1.5 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
            <button disabled={!newSubtask.trim()} aria-label="Add subtask" onClick={() => void addSubtask()} className="rounded-lg bg-accent p-1.5 text-white disabled:opacity-40"><Plus className="h-3.5 w-3.5" /></button>
          </div>
        </div>
        <div className="border-b border-border p-4 dark:border-border-dark">
          <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-text-primary dark:text-text-dark-primary"><CalendarClock className="h-3.5 w-3.5 text-accent" /> Schedule</h3>
          <div className="space-y-1">
            {schedules.map(sched => (
              <div key={sched.id} className="group flex items-center gap-2">
                <button onClick={() => void toggleSchedule(sched)} className={cn('h-4 w-7 flex-shrink-0 rounded-full p-0.5 transition-colors', sched.enabled ? 'bg-accent' : 'bg-surface-tertiary dark:bg-surface-dark-tertiary')} aria-label={sched.enabled ? 'Disable' : 'Enable'} title={sched.enabled ? 'Disable' : 'Enable'}><span className={cn('block h-3 w-3 rounded-full bg-white transition-transform', sched.enabled && 'translate-x-3')} /></button>
                <span className="flex flex-1 items-center gap-1 text-xs text-text-secondary dark:text-text-dark-secondary"><Clock3 className="h-3 w-3 text-text-tertiary" />{scheduleLabel(sched)}{sched.nextRunAt ? <span className="text-xs text-text-tertiary">· next {new Date(sched.nextRunAt).toLocaleString()}</span> : null}</span>
                <button aria-label="Remove schedule" onClick={() => void removeSchedule(sched)} className="flex-shrink-0 text-text-tertiary opacity-0 hover:text-red-500 group-hover:opacity-100"><X className="h-3 w-3" /></button>
              </div>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select value={schedCadence} onChange={e => setSchedCadence(e.target.value as 'interval' | 'daily' | 'weekly')} className="glass-input rounded-lg px-2 py-1.5 text-xs text-text-primary dark:text-text-dark-primary"><option value="interval">Interval</option><option value="daily">Daily</option><option value="weekly">Weekly</option></select>
            {schedCadence === 'interval'
              ? <input type="number" min={5} value={schedInterval} onChange={e => setSchedInterval(Number(e.target.value))} className="glass-input w-20 rounded-lg px-2 py-1.5 text-xs text-text-primary dark:text-text-dark-primary" title="Minutes" />
              : <input type="time" value={schedTime} onChange={e => setSchedTime(e.target.value)} className="glass-input rounded-lg px-2 py-1.5 text-xs text-text-primary dark:text-text-dark-primary" />}
            <button onClick={() => void addSchedule()} className="flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-semibold text-white"><Plus className="h-3.5 w-3.5" /> Schedule</button>
          </div>
          <p className="mt-1.5 text-xs text-text-tertiary">Runs with tools in {workspacePath ? 'the chosen folder' : 'no folder — pick one above for file changes'}.</p>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-4 scrollbar-thin">
          {runs.map(run => <section key={run.id} className="rounded-xl border border-border p-4 dark:border-border-dark"><div className="flex items-center gap-2"><Bot className="h-4 w-4 text-accent" /><span className="flex-1 text-xs font-semibold capitalize text-text-primary dark:text-text-dark-primary">{run.mode === 'agent' ? 'Dabba agent · tools enabled' : 'Dabba · safe run'}</span><span className={cn('rounded-full px-2 py-0.5 text-xs font-semibold uppercase', run.status === 'completed' ? 'bg-green-500/10 text-green-600' : run.status === 'failed' ? 'bg-red-500/10 text-red-500' : 'bg-amber-500/10 text-amber-600')}>{run.status}</span></div><p className="mt-1 text-xs text-text-tertiary">{new Date(run.startedAt).toLocaleString()}{run.workspacePath ? ` · ${run.workspacePath}` : ''}</p>{['queued', 'running'].includes(run.status) && <div className="mt-4 flex items-center gap-2 text-xs text-accent"><span className="h-2 w-2 animate-pulse rounded-full bg-accent" /> Cowork is completing this assignment…</div>}{run.output?.content && <pre className="mt-3 whitespace-pre-wrap break-words rounded-lg bg-surface-secondary p-3 font-sans text-xs leading-relaxed text-text-primary dark:bg-surface-dark-secondary dark:text-text-dark-primary">{run.output.content}</pre>}{run.output?.toolCallCount !== undefined && <p className="mt-2 text-xs text-text-tertiary">Tools used: {run.output.toolCallCount}{run.output.changedFiles?.length ? ` · Changed: ${run.output.changedFiles.join(', ')}` : ''}</p>}{run.error && <p className="mt-3 rounded-lg bg-red-500/10 p-3 text-xs text-red-500">{run.error}</p>}</section>)}
          {!runs.length && <div className="py-14 text-center text-xs text-text-tertiary"><Bot className="mx-auto mb-3 h-8 w-8 opacity-30" />No Cowork runs yet. Choose a run mode above.</div>}
        </div>
      </aside>
    </div>}
    <FolderPicker isOpen={folderPickerOpen} value={workspacePath} onClose={() => setFolderPickerOpen(false)} onSelect={setWorkspacePath} />
  </div>
}
