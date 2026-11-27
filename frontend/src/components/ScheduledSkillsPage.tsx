import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookOpenText, CalendarClock, ChevronDown, Clock3, Play, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { apiClient } from '@/api/client'
import { useModels } from '@/hooks/useModels'
import { useSettings } from '@/hooks/useSettings'
import { useSkills } from '@/hooks/useSkills'
import { dailyWordsInstructions, WORD_COUNTS, WORD_LEVELS, type WordLevel } from '@/lib/dailyWords'
import { loadMarkdownRenderer } from '@/lib/markdownRenderer'
import { cn } from '@/lib/utils'
import type { ScheduleCadence, ScheduledSkill, ScheduledSkillRun } from '@/types'

const MarkdownRenderer = lazy(loadMarkdownRenderer)

function cadenceLabel(schedule: ScheduledSkill) {
  if (schedule.cadence === 'interval') return `Every ${schedule.intervalMinutes} minutes`
  const local = `${schedule.timeOfDay ?? '09:00'} ${schedule.timeZone ?? 'UTC'}`
  if (schedule.cadence === 'daily') return `Daily at ${local}`
  return `Weekly at ${local}`
}

const FINISHED = ['completed', 'failed', 'cancelled']

function statusStyle(status: string) {
  if (status === 'completed') return { dot: 'bg-green-500', badge: 'bg-green-500/10 text-green-700 dark:text-green-400' }
  if (status === 'failed' || status === 'cancelled') return { dot: 'bg-red-500', badge: 'bg-red-500/10 text-red-600 dark:text-red-400' }
  return { dot: 'bg-amber-500', badge: 'bg-amber-500/10 text-amber-700 dark:text-amber-400' }
}

const fieldClass = 'glass-input w-full rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary'

export function ScheduledSkillsPage() {
  const { skills } = useSkills()
  const { models } = useModels()
  const { settings } = useSettings()
  const [schedules, setSchedules] = useState<ScheduledSkill[]>([])
  const [runs, setRuns] = useState<ScheduledSkillRun[]>([])
  const [name, setName] = useState('')
  const [skillId, setSkillId] = useState('')
  const [instructions, setInstructions] = useState('')
  const [model, setModel] = useState('')
  const [cadence, setCadence] = useState<ScheduleCadence>('daily')
  const [time, setTime] = useState('09:00')
  const [timeZone, setTimeZone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')
  const [interval, setIntervalValue] = useState(60)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')
  const [openRun, setOpenRun] = useState('')
  const autoOpened = useRef(false)

  // Quick start: "Daily new words".
  const [wordsLanguage, setWordsLanguage] = useState('English')
  const [wordsLevel, setWordsLevel] = useState<WordLevel>('Intermediate')
  const [wordsCount, setWordsCount] = useState<number>(5)

  // Only models that can actually run: the scheduler has no way to ask for a key.
  const usableModels = useMemo(() => models.filter(item => item.has_key), [models])
  // Default to the model picked in the chat, the way a message would run.
  useEffect(() => {
    if (!model && usableModels.some(item => item.id === settings.model)) setModel(settings.model)
  }, [model, usableModels, settings.model])
  const modelName = useCallback(
    (id?: string | null) => (id ? models.find(item => item.id === id)?.name ?? id : 'Server default'),
    [models],
  )

  const refresh = useCallback(async () => {
    setError('')
    try {
      const [nextSchedules, nextRuns] = await Promise.all([
        apiClient.listScheduledSkills(), apiClient.listScheduledSkillRuns(),
      ])
      setSchedules(nextSchedules); setRuns(nextRuns)
      // Open the newest result once, so the page shows something useful straight away.
      if (!autoOpened.current) {
        autoOpened.current = true
        const newest = nextRuns.find(item => item.status === 'completed' && item.output?.content)
        if (newest) setOpenRun(newest.id)
      }
    } catch (err) { setError((err as Error).message) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  // A run finishes on the server a little after it starts; keep checking until it does.
  const hasActiveRun = runs.some(item => !FINISHED.includes(item.status))
  useEffect(() => {
    if (!hasActiveRun) return
    const timer = setInterval(() => void refresh(), 3000)
    return () => clearInterval(timer)
  }, [hasActiveRun, refresh])

  const selectedSkill = useMemo(() => skills.find(skill => skill.id === skillId), [skillId, skills])
  useEffect(() => {
    if (selectedSkill) { setInstructions(selectedSkill.instructions); if (!name) setName(selectedSkill.name) }
  }, [selectedSkill, name])

  const useDailyWordsTemplate = () => {
    const language = wordsLanguage.trim() || 'English'
    setSkillId('')
    setName(`Daily new ${language} words`)
    setInstructions(dailyWordsInstructions({ language, level: wordsLevel, count: wordsCount }))
    setCadence('daily')
    setTime('08:00')
  }

  const create = async () => {
    if (!name.trim() || !instructions.trim()) return
    setBusyId('create'); setError('')
    try {
      const created = await apiClient.createScheduledSkill({
        name: name.trim(), skillName: selectedSkill?.name ?? name.trim(), instructions: instructions.trim(),
        model: model || null,
        cadence, intervalMinutes: cadence === 'interval' ? interval : null,
        timeOfDay: cadence === 'interval' ? null : time,
        timeZone: cadence === 'interval' ? 'UTC' : timeZone.trim(),
        weekdays: cadence === 'weekly' ? [0] : [],
        enabled: true,
      })
      setSchedules(previous => [created, ...previous]); setName(''); setInstructions(''); setSkillId('')
    } catch (err) { setError((err as Error).message) }
    finally { setBusyId('') }
  }

  const toggle = async (schedule: ScheduledSkill) => {
    try {
      const saved = await apiClient.updateScheduledSkill(schedule.id, { enabled: !schedule.enabled })
      setSchedules(previous => previous.map(item => item.id === saved.id ? saved : item))
    } catch (err) { setError((err as Error).message) }
  }

  const run = async (schedule: ScheduledSkill) => {
    setBusyId(schedule.id)
    try {
      const result = await apiClient.runScheduledSkill(schedule.id)
      setRuns(previous => [result, ...previous])
      setOpenRun(result.id) // shows "working on it", then the result once polling sees it finish
      await refresh()
    }
    catch (err) { setError((err as Error).message) }
    finally { setBusyId('') }
  }

  const remove = async (id: string) => {
    try { await apiClient.deleteScheduledSkill(id); setSchedules(previous => previous.filter(item => item.id !== id)) }
    catch (err) { setError((err as Error).message) }
  }

  return <div className="h-full overflow-y-auto scrollbar-thin">
    <header className="flex items-center justify-between border-b border-border px-4 py-4 dark:border-border-dark sm:px-6">
      <div>
        <h1 className="flex items-center gap-2 text-sm font-bold text-text-primary dark:text-text-dark-primary"><CalendarClock className="h-4 w-4 text-accent" /> Scheduled skills</h1>
        <p className="mt-1 text-xs text-text-secondary dark:text-text-dark-secondary">Run reusable instructions automatically, with durable queueing and history.</p>
      </div>
      <button onClick={() => void refresh()} aria-label="Refresh" className="rounded-lg p-2 text-text-secondary hover:bg-surface-secondary dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary"><RefreshCw className="h-4 w-4" /></button>
    </header>

    <div className="grid gap-5 p-4 sm:p-6 lg:grid-cols-[360px_1fr]">
      <section className="h-fit rounded-2xl border border-border bg-surface-secondary p-4 dark:border-border-dark dark:bg-surface-dark-secondary">
        <div className="mb-4 rounded-xl border border-dashed border-accent/40 bg-accent/5 p-3">
          <h2 className="flex items-center gap-1.5 text-xs font-semibold text-text-primary dark:text-text-dark-primary"><BookOpenText className="h-3.5 w-3.5 text-accent" /> Quick start: daily new words</h2>
          <p className="mt-1 text-[11px] text-text-secondary dark:text-text-dark-secondary">A fresh set of words with meanings and examples every morning. Each day avoids the words it already sent.</p>
          <div className="mt-2.5 grid grid-cols-3 gap-2">
            <input aria-label="Language" value={wordsLanguage} onChange={event => setWordsLanguage(event.target.value)} placeholder="Language" className={cn(fieldClass, 'col-span-3')} />
            <select aria-label="Level" value={wordsLevel} onChange={event => setWordsLevel(event.target.value as WordLevel)} className={cn(fieldClass, 'col-span-2')}>
              {WORD_LEVELS.map(level => <option key={level} value={level}>{level}</option>)}
            </select>
            <select aria-label="Words per day" value={wordsCount} onChange={event => setWordsCount(Number(event.target.value))} className={fieldClass}>
              {WORD_COUNTS.map(count => <option key={count} value={count}>{count} words</option>)}
            </select>
          </div>
          <button type="button" onClick={useDailyWordsTemplate} className="mt-2.5 w-full rounded-lg border border-accent/50 px-3 py-2 text-xs font-semibold text-accent hover:bg-accent/10">Use this template</button>
        </div>

        <h2 className="mb-3 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Create automation</h2>
        <div className="space-y-3">
          <input value={name} onChange={event => setName(event.target.value)} placeholder="Schedule name" className={fieldClass} />
          <select value={skillId} onChange={event => setSkillId(event.target.value)} aria-label="Skill" className={fieldClass}>
            <option value="">Custom instructions</option>{skills.map(skill => <option key={skill.id} value={skill.id}>{skill.name}</option>)}
          </select>
          <textarea value={instructions} onChange={event => setInstructions(event.target.value)} placeholder="What should this skill do?" rows={5} className={cn(fieldClass, 'resize-none')} />
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-text-secondary dark:text-text-dark-secondary">Model</span>
            <select value={model} onChange={event => setModel(event.target.value)} className={fieldClass}>
              <option value="">Server default</option>
              {usableModels.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <select value={cadence} onChange={event => setCadence(event.target.value as ScheduleCadence)} aria-label="How often" className="glass-input rounded-lg px-2 py-2 text-xs text-text-primary dark:text-text-dark-primary"><option value="interval">Interval</option><option value="daily">Daily</option><option value="weekly">Weekly</option></select>
            {cadence === 'interval' ? <input type="number" min={5} value={interval} onChange={event => setIntervalValue(Number(event.target.value))} aria-label="Minutes" className="glass-input rounded-lg px-3 py-2 text-xs text-text-primary dark:text-text-dark-primary" /> : <input type="time" value={time} onChange={event => setTime(event.target.value)} aria-label="Time of day" className="glass-input rounded-lg px-3 py-2 text-xs text-text-primary dark:text-text-dark-primary" />}
          </div>
          {cadence !== 'interval' && (
            <label className="block text-xs">
              Time zone
              <input aria-label="Schedule time zone" value={timeZone} onChange={event => setTimeZone(event.target.value)} className={fieldClass} placeholder="Asia/Kolkata" />
            </label>
          )}
          <p className="text-[10px] text-text-tertiary">After downtime, Dabba runs a missed schedule once, then resumes its regular cadence.</p>
          <button disabled={!name.trim() || !instructions.trim() || busyId === 'create'} onClick={() => void create()} className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"><Plus className="h-3.5 w-3.5" /> Create schedule</button>
          {error && <p role="alert" className="text-xs text-red-500">{error}</p>}
        </div>
      </section>

      <div className="min-w-0 space-y-5">
        <section>
          <h2 className="mb-2 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Automations ({schedules.length})</h2>
          <div className="space-y-2">
            {schedules.map(schedule => <article key={schedule.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface-secondary p-3 dark:border-border-dark dark:bg-surface-dark-secondary">
              <button onClick={() => void toggle(schedule)} aria-label={schedule.enabled ? 'Disable' : 'Enable'} className={`h-5 w-9 rounded-full p-0.5 transition-colors ${schedule.enabled ? 'bg-accent' : 'bg-surface-tertiary dark:bg-surface-dark-tertiary'}`} title={schedule.enabled ? 'Disable' : 'Enable'}><span className={`block h-4 w-4 rounded-full bg-white transition-transform ${schedule.enabled ? 'translate-x-4' : ''}`} /></button>
              <div className="min-w-0 flex-1"><h3 className="truncate text-xs font-semibold text-text-primary dark:text-text-dark-primary">{schedule.name}</h3><p className="mt-0.5 flex flex-wrap items-center gap-x-1 text-[10px] text-text-tertiary"><Clock3 className="h-3 w-3" />{cadenceLabel(schedule)} · Next {schedule.nextRunAt ? new Date(schedule.nextRunAt).toLocaleString() : 'not scheduled'} · {modelName(schedule.model)}</p></div>
              <button disabled={busyId === schedule.id} onClick={() => void run(schedule)} className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-[10px] font-semibold text-text-secondary hover:text-accent dark:border-border-dark dark:text-text-dark-secondary"><Play className="h-3 w-3" /> Run now</button>
              <button onClick={() => void remove(schedule.id)} aria-label="Delete schedule" className="p-1.5 text-text-tertiary hover:text-red-500"><Trash2 className="h-3.5 w-3.5" /></button>
            </article>)}
            {!schedules.length && <div className="rounded-xl border border-dashed border-border p-10 text-center text-xs text-text-tertiary dark:border-border-dark">No scheduled skills yet. Try the daily new words quick start.</div>}
          </div>
        </section>
        <section>
          <h2 className="mb-2 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Recent runs</h2>
          <div className="overflow-hidden rounded-xl border border-border dark:border-border-dark">
            {runs.slice(0, 10).map(runItem => {
              const style = statusStyle(runItem.status)
              const open = openRun === runItem.id
              const result = runItem.output?.content ?? runItem.output?.message ?? ''
              const working = !FINISHED.includes(runItem.status)
              return <div key={runItem.id} className="border-b border-border last:border-0 dark:border-border-dark">
                <button type="button" aria-expanded={open} onClick={() => setOpenRun(open ? '' : runItem.id)} className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-secondary dark:hover:bg-surface-dark-tertiary">
                  <span className={`h-2 w-2 flex-shrink-0 rounded-full ${style.dot}`} />
                  <span className="min-w-0 flex-1 truncate text-[11px] text-text-secondary dark:text-text-dark-secondary">{schedules.find(item => item.id === runItem.scheduleId)?.name ?? 'Scheduled skill'} · {runItem.triggeredBy}</span>
                  <span className="hidden text-[10px] text-text-tertiary sm:inline">{new Date(runItem.startedAt).toLocaleString()}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase ${style.badge}`}>{runItem.status}</span>
                  <ChevronDown className={cn('h-3.5 w-3.5 flex-shrink-0 text-text-tertiary transition-transform', open && 'rotate-180')} />
                </button>
                {open && <div className="px-4 pb-4 pt-1 text-sm">
                  {runItem.error
                    ? <p className="text-xs text-red-500">{runItem.error}</p>
                    : result
                      ? <Suspense fallback={<p className="text-xs text-text-tertiary">Loading…</p>}><MarkdownRenderer content={result} /></Suspense>
                      : <p className="text-xs text-text-tertiary">{working ? 'Working on it. The result will appear here.' : 'No result was saved for this run.'}</p>}
                </div>}
              </div>
            })}
            {!runs.length && <p className="p-5 text-center text-[11px] text-text-tertiary">Run history will appear here.</p>}
          </div>
        </section>
      </div>
    </div>
  </div>
}
