import { useCallback, useEffect, useMemo, useState } from 'react'
import { Ban, Bot, CheckCircle2, ClipboardList, FolderOpen, Loader2, Plus, RotateCcw, Send, ShieldCheck, Sparkles, X, XCircle } from 'lucide-react'
import { apiClient } from '@/api/client'
import type { CoworkItem, CoworkRun, PlatformTask, PlatformTaskEvent } from '@/types'
import { CoworkPage as CoworkBoard } from './CoworkPage'
import { FolderPicker } from './FolderPicker'
import { ModelSwitcher } from './ModelSwitcher'
import { cn } from '@/lib/utils'
import { useSettings } from '@/hooks/useSettings'
import { useRunNotifications } from '@/hooks/useRunNotifications'

export function CoworkWorkspace() {
  const { settings } = useSettings()
  const [section, setSection] = useState<'new' | 'tasks'>('new')
  const [prompt, setPrompt] = useState('')
  const [workspacePath, setWorkspacePath] = useState('')
  const [folderPickerOpen, setFolderPickerOpen] = useState(false)
  const [toolsEnabled, setToolsEnabled] = useState(true)
  const [items, setItems] = useState<CoworkItem[]>([])
  const [activeItem, setActiveItem] = useState<CoworkItem | null>(null)
  const [activeRun, setActiveRun] = useState<CoworkRun | null>(null)
  const [liveTask, setLiveTask] = useState<PlatformTask | null>(null)
  const [liveEvents, setLiveEvents] = useState<PlatformTaskEvent[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const { notices, dismiss } = useRunNotifications(items)

  const refreshItems = useCallback(async () => {
    try { setItems(await apiClient.listCoworkItems()) }
    catch (err) { setError((err as Error).message) }
  }, [])
  useEffect(() => { void refreshItems() }, [refreshItems])

  // Always-on lightweight poll so run-completion notifications fire board-wide,
  // regardless of which tab is open or whether a run is being actively watched.
  useEffect(() => {
    const timer = window.setInterval(() => { void refreshItems() }, 3000)
    return () => window.clearInterval(timer)
  }, [refreshItems])

  useEffect(() => {
    if (!activeItem || !activeRun || !['queued', 'running'].includes(activeRun.status)) return
    const timer = window.setInterval(async () => {
      try {
        const [runs, nextItems, task, events] = await Promise.all([
          apiClient.listCoworkRuns(activeItem.id), apiClient.listCoworkItems(),
          apiClient.getPlatformTask(activeRun.taskId),
          apiClient.listPlatformTaskEvents(activeRun.taskId),
        ])
        const nextRun = runs.find(run => run.id === activeRun.id)
        if (nextRun) setActiveRun(nextRun)
        const nextItem = nextItems.find(item => item.id === activeItem.id)
        if (nextItem) setActiveItem(nextItem)
        setItems(nextItems); setLiveTask(task); setLiveEvents(events)
      } catch (err) { setError((err as Error).message) }
    }, 2200)
    return () => window.clearInterval(timer)
  }, [activeItem, activeRun])

  const recentItems = useMemo(() => items.slice(0, 5), [items])

  const runAssignment = async () => {
    const instructions = prompt.trim()
    if (!instructions || busy) return
    setBusy(true); setError(''); setActiveRun(null); setLiveTask(null); setLiveEvents([])
    try {
      const title = instructions.split('\n')[0].slice(0, 90) || 'Cowork assignment'
      const item = await apiClient.createCoworkItem({
        title, description: instructions, priority: 'medium', status: 'planned', assignee: 'Dabba',
      })
      const run = await apiClient.runCoworkItem(item.id, {
        mode: toolsEnabled ? 'agent' : 'safe',
        model: settings.model,
        effort: settings.effort,
        ...(toolsEnabled && workspacePath ? { workspacePath } : {}),
      })
      setActiveItem({ ...item, status: 'in_progress' }); setActiveRun(run)
      const [task, events] = await Promise.all([
        apiClient.getPlatformTask(run.taskId), apiClient.listPlatformTaskEvents(run.taskId),
      ])
      setLiveTask(task); setLiveEvents(events)
      setItems(previous => [{ ...item, status: 'in_progress' }, ...previous]); setPrompt('')
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  const openRecent = async (item: CoworkItem) => {
    setActiveItem(item); setError('')
    try {
      const runs = await apiClient.listCoworkRuns(item.id)
      const run = runs[0] ?? null
      setActiveRun(run)
      if (run) {
        const previousWorkspace = runs.find(candidate => candidate.workspacePath)?.workspacePath
        if (previousWorkspace) setWorkspacePath(previousWorkspace)
        const [task, events] = await Promise.all([
          apiClient.getPlatformTask(run.taskId), apiClient.listPlatformTaskEvents(run.taskId),
        ])
        setLiveTask(task); setLiveEvents(events)
      } else {
        setLiveTask(null); setLiveEvents([])
      }
    }
    catch (err) { setError((err as Error).message) }
  }

  const continueWithTools = async () => {
    if (!activeItem || busy) return
    const path = activeRun?.workspacePath || workspacePath
    if (!path) {
      setError('Choose the existing project folder before continuing with tools.')
      setFolderPickerOpen(true)
      return
    }
    setBusy(true); setError(''); setLiveTask(null); setLiveEvents([])
    try {
      const run = await apiClient.runCoworkItem(activeItem.id, {
        mode: 'agent', workspacePath: path, model: settings.model, effort: settings.effort,
      })
      const [task, events] = await Promise.all([
        apiClient.getPlatformTask(run.taskId), apiClient.listPlatformTaskEvents(run.taskId),
      ])
      setActiveRun(run); setLiveTask(task); setLiveEvents(events)
      setActiveItem({ ...activeItem, status: 'in_progress' })
      setItems(previous => previous.map(item => item.id === activeItem.id ? { ...item, status: 'in_progress' } : item))
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  const stopActiveRun = async () => {
    if (!activeRun || !['queued', 'running'].includes(activeRun.status) || busy) return
    setBusy(true); setError('')
    try {
      const stopped = await apiClient.cancelCoworkRun(activeRun.id)
      setActiveRun(stopped)
      setLiveTask(previous => previous ? { ...previous, status: 'cancelled', currentStep: 'Stopped by user' } : previous)
      if (activeItem) {
        const planned = { ...activeItem, status: 'planned' as const }
        setActiveItem(planned)
        setItems(previous => previous.map(item => item.id === planned.id ? planned : item))
      }
      await refreshItems()
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  const activityEvents = liveEvents.filter(event => event.type.startsWith('cowork.')).slice(-20)

  const activityText = (event: PlatformTaskEvent) => {
    const payload = event.payload
    if (event.type === 'cowork.note') return String(payload.content || '')
    if (event.type === 'cowork.tool.started') {
      const details = Object.values((payload.arguments as Record<string, unknown>) || {}).filter(Boolean).join(' · ')
      return `Using ${String(payload.tool || 'tool')}${details ? ` — ${details}` : ''}`
    }
    if (event.type === 'cowork.tool.finished') {
      return `${payload.success ? 'Finished' : 'Failed'} ${String(payload.tool || 'tool')}${payload.error ? ` — ${String(payload.error)}` : ''}`
    }
    if (event.type === 'cowork.provider.fallback') {
      return `Model ${String(payload.model || '')} failed — switched to ${String(payload.nextModel || 'fallback')}`
    }
    return event.type.replace(/^cowork\./, '').replace(/\./g, ' ')
  }

  return <div className="flex h-full min-h-0 flex-col overflow-hidden bg-surface dark:bg-surface-dark">
    {notices.length > 0 && (
      <div className="pointer-events-none fixed right-4 top-4 z-50 flex w-80 flex-col gap-2">
        {notices.map(notice => (
          <div key={notice.id} className={cn(
            'pointer-events-auto flex items-start gap-2 rounded-xl border p-3 text-xs shadow-lg backdrop-blur',
            notice.tone === 'success' ? 'border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-300'
              : notice.tone === 'error' ? 'border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-300'
                : 'border-border bg-surface/95 text-text-secondary dark:border-border-dark dark:bg-surface-dark-secondary/95 dark:text-text-dark-secondary'
          )}>
            {notice.tone === 'success' ? <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
              : notice.tone === 'error' ? <XCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                : <Bot className="mt-0.5 h-4 w-4 flex-shrink-0" />}
            <span className="flex-1">{notice.message}</span>
            <button aria-label="Dismiss notification" onClick={() => dismiss(notice.id)} className="text-current opacity-60 hover:opacity-100"><X className="h-3.5 w-3.5" /></button>
          </div>
        ))}
      </div>
    )}
    <header className="flex flex-shrink-0 items-center justify-between border-b border-border px-5 py-2.5 dark:border-border-dark">
      <div className="flex items-center gap-2 text-xs font-semibold text-text-primary dark:text-text-dark-primary"><Sparkles className="h-4 w-4 text-accent" /> Cowork</div>
      <div className="flex items-center gap-1 rounded-lg bg-surface-secondary p-1 dark:bg-surface-dark-secondary">
        <button onClick={() => setSection('new')} className={cn('flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[11px] font-medium', section === 'new' ? 'bg-surface text-accent shadow-sm dark:bg-surface-dark-tertiary' : 'text-text-secondary dark:text-text-dark-secondary')}><Plus className="h-3.5 w-3.5" /> New task</button>
        <button onClick={() => setSection('tasks')} className={cn('flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[11px] font-medium', section === 'tasks' ? 'bg-surface text-accent shadow-sm dark:bg-surface-dark-tertiary' : 'text-text-secondary dark:text-text-dark-secondary')}><ClipboardList className="h-3.5 w-3.5" /> Task board</button>
      </div>
    </header>

    {section === 'tasks' ? <div className="min-h-0 flex-1"><CoworkBoard /></div> : <main className="relative min-h-0 flex-1 overflow-y-auto scrollbar-thin">
      <div className="pointer-events-none absolute inset-0 opacity-[0.12] dark:opacity-[0.16]" style={{ backgroundImage: 'radial-gradient(circle, currentColor 1.2px, transparent 1.2px)', backgroundSize: '28px 28px', color: '#809080', maskImage: 'radial-gradient(ellipse at center, black 20%, transparent 72%)' }} />
      <div className="relative mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-5 py-12">
        <div className="mb-7 flex items-center justify-center gap-3"><Sparkles className="h-7 w-7 text-accent" /><div><h1 className="text-2xl font-semibold tracking-tight text-text-primary dark:text-text-dark-primary sm:text-3xl">What can I take off your plate?</h1><p className="mt-1 text-xs text-text-tertiary">Describe the result you need. Dabba will work on it and report back.</p></div></div>

        <section className="overflow-visible rounded-2xl border border-border bg-surface shadow-xl shadow-black/5 dark:border-border-dark dark:bg-surface-dark-secondary dark:shadow-black/20">
          <textarea value={prompt} onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void runAssignment() } }} placeholder="How can I help you today?" rows={5} className="w-full resize-none bg-transparent px-5 pt-5 text-sm text-text-primary outline-none placeholder:text-text-tertiary dark:text-text-dark-primary" />
          <div className="flex items-center gap-2 px-4 pb-3"><button onClick={() => setFolderPickerOpen(true)} className="rounded-lg p-2 text-text-secondary hover:bg-surface-secondary hover:text-accent dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary" aria-label="Choose project or folder" title="Choose project or folder"><Plus className="h-4 w-4" /></button><div className="flex-1" /><ModelSwitcher /><button disabled={!prompt.trim() || busy} onClick={() => void runAssignment()} className="rounded-lg bg-accent p-2 text-white hover:bg-accent-hover disabled:opacity-35" title="Start Cowork task">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</button></div>
          <div className="border-t border-border dark:border-border-dark"><button onClick={() => setFolderPickerOpen(true)} className="flex w-full items-center gap-2 px-5 py-2.5 text-left text-xs text-text-secondary hover:bg-surface-secondary/60 dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary/60"><FolderOpen className="h-4 w-4" /><span className="min-w-0 flex-1 truncate">{workspacePath || 'Work in a project or folder'}</span><span className="text-text-tertiary">⌄</span></button><div className="flex items-center justify-between border-t border-border/70 px-5 py-2 text-[10px] text-text-tertiary dark:border-border-dark/70"><button onClick={() => setToolsEnabled(value => !value)} className={cn('flex items-center gap-1.5 font-medium', toolsEnabled && 'text-accent')}><ShieldCheck className="h-3.5 w-3.5" />{toolsEnabled ? 'Tools and connectors enabled' : 'Safe model-only mode'}</button><span>Enter to send · Shift+Enter for new line</span></div></div>
        </section>
        {error && <p className="mt-3 rounded-lg bg-red-500/10 p-3 text-xs text-red-500">{error}</p>}

        {activeItem && <section className="mt-5 rounded-2xl border border-border bg-surface/95 p-5 shadow-lg dark:border-border-dark dark:bg-surface-dark-secondary/95">
          <div className="flex items-center gap-3">
            <span className={cn('flex h-8 w-8 items-center justify-center rounded-full', activeRun?.status === 'completed' ? 'bg-green-500/10 text-green-600' : activeRun?.status === 'failed' ? 'bg-red-500/10 text-red-500' : 'bg-accent/10 text-accent')}>{activeRun?.status === 'completed' ? <CheckCircle2 className="h-4 w-4" /> : <Bot className="h-4 w-4" />}</span>
            <div className="min-w-0 flex-1"><h2 className="truncate text-sm font-semibold text-text-primary dark:text-text-dark-primary">{activeItem.title}</h2><p className="text-[10px] capitalize text-text-tertiary">{activeRun?.status || activeItem.status}{activeRun?.mode === 'agent' ? ' · tools enabled' : ''}</p></div>
            {activeRun && ['queued', 'running'].includes(activeRun.status) && <div className="flex items-center gap-2"><span className="flex items-center gap-1.5 text-[10px] font-medium text-accent"><span className="h-2 w-2 animate-pulse rounded-full bg-accent" />Working</span><button disabled={busy} onClick={() => void stopActiveRun()} className="flex items-center gap-1 rounded-lg bg-red-500/10 px-2.5 py-1.5 text-[10px] font-semibold text-red-500 hover:bg-red-500/20 disabled:opacity-50">{busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Ban className="h-3 w-3" />} Stop task</button></div>}
          </div>

          {liveTask && <div className="mt-4 rounded-xl border border-border bg-surface-secondary/60 p-3 dark:border-border-dark dark:bg-surface-dark-tertiary/60">
            <div className="flex items-center justify-between gap-3 text-[10px]"><span className="font-semibold text-text-primary dark:text-text-dark-primary">Live activity</span><span className="text-text-tertiary">{Math.round(liveTask.progress * 100)}%</span></div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-black/10 dark:bg-white/10"><div className="h-full rounded-full bg-accent transition-all duration-500" style={{ width: `${Math.max(3, liveTask.progress * 100)}%` }} /></div>
            <p className="mt-2 flex items-center gap-2 text-[11px] font-medium text-accent">{['queued', 'running'].includes(liveTask.status) && <Loader2 className="h-3 w-3 animate-spin" />}{liveTask.currentStep || 'Preparing the assignment'}</p>
            {activityEvents.length > 0 && <div className="mt-3 max-h-52 space-y-2 overflow-y-auto border-t border-border pt-3 scrollbar-thin dark:border-border-dark">
              {activityEvents.map(event => <div key={event.id} className="flex gap-2 text-[10px]"><span className={cn('mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full', event.type === 'cowork.tool.finished' && event.payload.success === false ? 'bg-red-500' : event.type === 'cowork.tool.finished' ? 'bg-green-500' : 'bg-accent')} /><div className="min-w-0"><p className="break-words text-text-secondary dark:text-text-dark-secondary">{activityText(event)}</p><time className="text-[9px] text-text-tertiary">{new Date(event.createdAt).toLocaleTimeString()}</time></div></div>)}
            </div>}
          </div>}

          {activeRun?.output?.content && <div className="mt-4 whitespace-pre-wrap text-xs leading-relaxed text-text-primary dark:text-text-dark-primary">{activeRun.output.content}</div>}
          {activeRun?.error && <p className="mt-3 text-xs text-red-500">{activeRun.error}</p>}
          {activeRun?.output?.changedFiles?.length ? <p className="mt-3 text-[10px] text-text-tertiary">Changed files: {activeRun.output.changedFiles.join(', ')}</p> : null}
          {activeRun?.mode === 'safe' && <p className="mt-3 rounded-lg bg-amber-500/10 p-3 text-[10px] text-amber-700 dark:text-amber-400">This was a safe model-only run. It could describe the work but could not create or edit project files.</p>}
          {activeRun && ['completed', 'failed', 'cancelled'].includes(activeRun.status) && <button disabled={busy} onClick={() => void continueWithTools()} className="mt-4 flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-50">{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />} Continue with tools</button>}
        </section>}

        {!activeItem && recentItems.length > 0 && <section className="mt-6"><p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">Recent Cowork tasks</p><div className="grid gap-2 sm:grid-cols-2">{recentItems.map(item => <button key={item.id} onClick={() => void openRecent(item)} className="flex items-center gap-2 rounded-xl border border-border bg-surface/80 p-3 text-left hover:border-accent/50 dark:border-border-dark dark:bg-surface-dark-secondary/80"><span className={cn('h-2 w-2 rounded-full', item.status === 'done' ? 'bg-green-500' : item.status === 'blocked' ? 'bg-red-500' : item.status === 'in_progress' ? 'animate-pulse bg-accent' : 'bg-text-tertiary')} /><span className="min-w-0 flex-1 truncate text-xs text-text-primary dark:text-text-dark-primary">{item.title}</span><span className="text-[9px] capitalize text-text-tertiary">{item.status.replace(/_/g, ' ')}</span></button>)}</div></section>}
      </div>
    </main>}
    <FolderPicker isOpen={folderPickerOpen} value={workspacePath} onClose={() => setFolderPickerOpen(false)} onSelect={setWorkspacePath} />
  </div>
}
