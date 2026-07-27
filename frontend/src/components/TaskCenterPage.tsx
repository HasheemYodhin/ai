import { useCallback, useEffect, useState } from 'react'
import { Ban, ListChecks, RefreshCw, RotateCcw } from 'lucide-react'
import { apiClient } from '@/api/client'
import type { PlatformTask } from '@/types'
import { cn } from '@/lib/utils'

const statusTone: Record<PlatformTask['status'], string> = {
  queued: 'bg-slate-500/10 text-slate-500', planning: 'bg-blue-500/10 text-blue-500',
  running: 'bg-accent/10 text-accent', waiting_for_approval: 'bg-amber-500/10 text-amber-600',
  retrying: 'bg-violet-500/10 text-violet-500', completed: 'bg-green-500/10 text-green-600',
  failed: 'bg-red-500/10 text-red-500', cancelled: 'bg-slate-500/10 text-slate-500',
}

export function TaskCenterPage() {
  const [tasks, setTasks] = useState<PlatformTask[]>([])
  const [error, setError] = useState('')
  const refresh = useCallback(async () => {
    setError('')
    try { setTasks(await apiClient.listPlatformTasks()) }
    catch (err) { setError((err as Error).message) }
  }, [])
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 5000); return () => window.clearInterval(timer) }, [refresh])

  const cancel = async (task: PlatformTask) => {
    try { const saved = await apiClient.cancelPlatformTask(task.id); setTasks(previous => previous.map(item => item.id === saved.id ? saved : item)) }
    catch (err) { setError((err as Error).message) }
  }
  const resume = async (task: PlatformTask) => {
    try { const saved = await apiClient.resumePlatformTask(task.id); setTasks(previous => previous.map(item => item.id === saved.id ? saved : item)) }
    catch (err) { setError((err as Error).message) }
  }

  return <div className="h-full overflow-y-auto scrollbar-thin">
    <header className="flex items-center justify-between border-b border-border px-6 py-4 dark:border-border-dark">
      <div><h1 className="flex items-center gap-2 text-sm font-bold text-text-primary dark:text-text-dark-primary"><ListChecks className="h-4 w-4 text-accent" /> Task center</h1><p className="mt-1 text-xs text-text-secondary dark:text-text-dark-secondary">Monitor chats, agents, and scheduled skill runs.</p></div>
      <button onClick={() => void refresh()} className="rounded-lg p-2 text-text-secondary hover:bg-surface-secondary dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary"><RefreshCw className="h-4 w-4" /></button>
    </header>
    <div className="p-6">
      {error && <p className="mb-3 text-xs text-red-500">{error}</p>}
      <div className="overflow-hidden rounded-2xl border border-border dark:border-border-dark">
        {tasks.map(task => <article key={task.id} className="border-b border-border p-4 last:border-0 dark:border-border-dark">
          <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-0 flex-1"><h2 className="truncate text-xs font-semibold capitalize text-text-primary dark:text-text-dark-primary">{task.kind.replace(/_/g, ' ')}</h2><p className="mt-1 text-[10px] text-text-tertiary">{task.currentStep || new Date(task.createdAt).toLocaleString()} · {task.id}</p></div>
            <span className={cn('rounded-full px-2 py-1 text-[9px] font-semibold uppercase', statusTone[task.status])}>{task.status.replace(/_/g, ' ')}</span>
            {['queued', 'planning', 'running', 'waiting_for_approval', 'retrying'].includes(task.status) && <button onClick={() => void cancel(task)} className="rounded-lg p-1.5 text-text-tertiary hover:bg-red-500/10 hover:text-red-500" title="Cancel"><Ban className="h-3.5 w-3.5" /></button>}
            {['failed', 'cancelled'].includes(task.status) && <button onClick={() => void resume(task)} className="rounded-lg p-1.5 text-text-tertiary hover:bg-accent/10 hover:text-accent" title="Retry"><RotateCcw className="h-3.5 w-3.5" /></button>}
          </div>
          {task.status === 'running' && <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-tertiary dark:bg-surface-dark-tertiary"><div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.max(3, task.progress * 100)}%` }} /></div>}
          {task.error?.message && <p className="mt-2 text-[11px] text-red-500">{task.error.message}</p>}
        </article>)}
        {!tasks.length && <div className="p-14 text-center text-xs text-text-tertiary">No durable tasks yet.</div>}
      </div>
    </div>
  </div>
}
