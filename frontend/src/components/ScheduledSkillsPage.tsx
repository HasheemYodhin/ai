import { useCallback, useEffect, useMemo, useState } from 'react'
import { CalendarClock, Clock3, Play, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { apiClient } from '@/api/client'
import { useSkills } from '@/hooks/useSkills'
import type { ScheduleCadence, ScheduledSkill, ScheduledSkillRun } from '@/types'

function cadenceLabel(schedule: ScheduledSkill) {
  if (schedule.cadence === 'interval') return `Every ${schedule.intervalMinutes} minutes`
  if (schedule.cadence === 'daily') return `Daily at ${schedule.timeOfDay}`
  return `Weekly at ${schedule.timeOfDay}`
}

export function ScheduledSkillsPage() {
  const { skills } = useSkills()
  const [schedules, setSchedules] = useState<ScheduledSkill[]>([])
  const [runs, setRuns] = useState<ScheduledSkillRun[]>([])
  const [name, setName] = useState('')
  const [skillId, setSkillId] = useState('')
  const [instructions, setInstructions] = useState('')
  const [cadence, setCadence] = useState<ScheduleCadence>('daily')
  const [time, setTime] = useState('09:00')
  const [interval, setIntervalValue] = useState(60)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')

  const refresh = useCallback(async () => {
    setError('')
    try {
      const [nextSchedules, nextRuns] = await Promise.all([
        apiClient.listScheduledSkills(), apiClient.listScheduledSkillRuns(),
      ])
      setSchedules(nextSchedules); setRuns(nextRuns)
    } catch (err) { setError((err as Error).message) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const selectedSkill = useMemo(() => skills.find(skill => skill.id === skillId), [skillId, skills])
  useEffect(() => {
    if (selectedSkill) { setInstructions(selectedSkill.instructions); if (!name) setName(selectedSkill.name) }
  }, [selectedSkill, name])

  const create = async () => {
    if (!name.trim() || !instructions.trim()) return
    setBusyId('create'); setError('')
    try {
      const created = await apiClient.createScheduledSkill({
        name: name.trim(), skillName: selectedSkill?.name ?? name.trim(), instructions: instructions.trim(),
        cadence, intervalMinutes: cadence === 'interval' ? interval : null,
        timeOfDay: cadence === 'interval' ? null : time, weekdays: cadence === 'weekly' ? [0] : [], enabled: true,
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
    try { const result = await apiClient.runScheduledSkill(schedule.id); setRuns(previous => [result, ...previous]); await refresh() }
    catch (err) { setError((err as Error).message) }
    finally { setBusyId('') }
  }

  const remove = async (id: string) => {
    try { await apiClient.deleteScheduledSkill(id); setSchedules(previous => previous.filter(item => item.id !== id)) }
    catch (err) { setError((err as Error).message) }
  }

  return <div className="h-full overflow-y-auto scrollbar-thin">
    <header className="flex items-center justify-between border-b border-border px-6 py-4 dark:border-border-dark">
      <div>
        <h1 className="flex items-center gap-2 text-sm font-bold text-text-primary dark:text-text-dark-primary"><CalendarClock className="h-4 w-4 text-accent" /> Scheduled skills</h1>
        <p className="mt-1 text-xs text-text-secondary dark:text-text-dark-secondary">Run reusable instructions automatically, with durable queueing and history.</p>
      </div>
      <button onClick={() => void refresh()} className="rounded-lg p-2 text-text-secondary hover:bg-surface-secondary dark:text-text-dark-secondary dark:hover:bg-surface-dark-tertiary"><RefreshCw className="h-4 w-4" /></button>
    </header>

    <div className="grid gap-5 p-6 lg:grid-cols-[360px_1fr]">
      <section className="h-fit rounded-2xl border border-border bg-surface-secondary p-4 dark:border-border-dark dark:bg-surface-dark-secondary">
        <h2 className="mb-3 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Create automation</h2>
        <div className="space-y-3">
          <input value={name} onChange={event => setName(event.target.value)} placeholder="Schedule name" className="glass-input w-full rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
          <select value={skillId} onChange={event => setSkillId(event.target.value)} className="glass-input w-full rounded-lg px-3 py-2 text-xs text-text-primary dark:text-text-dark-primary">
            <option value="">Custom instructions</option>{skills.map(skill => <option key={skill.id} value={skill.id}>{skill.name}</option>)}
          </select>
          <textarea value={instructions} onChange={event => setInstructions(event.target.value)} placeholder="What should this skill do?" rows={5} className="glass-input w-full resize-none rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
          <div className="grid grid-cols-2 gap-2">
            <select value={cadence} onChange={event => setCadence(event.target.value as ScheduleCadence)} className="glass-input rounded-lg px-2 py-2 text-xs text-text-primary dark:text-text-dark-primary"><option value="interval">Interval</option><option value="daily">Daily</option><option value="weekly">Weekly</option></select>
            {cadence === 'interval' ? <input type="number" min={5} value={interval} onChange={event => setIntervalValue(Number(event.target.value))} className="glass-input rounded-lg px-3 py-2 text-xs text-text-primary dark:text-text-dark-primary" /> : <input type="time" value={time} onChange={event => setTime(event.target.value)} className="glass-input rounded-lg px-3 py-2 text-xs text-text-primary dark:text-text-dark-primary" />}
          </div>
          <button disabled={!name.trim() || !instructions.trim() || busyId === 'create'} onClick={() => void create()} className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"><Plus className="h-3.5 w-3.5" /> Create schedule</button>
          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>
      </section>

      <div className="space-y-5">
        <section>
          <h2 className="mb-2 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Automations ({schedules.length})</h2>
          <div className="space-y-2">
            {schedules.map(schedule => <article key={schedule.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface-secondary p-3 dark:border-border-dark dark:bg-surface-dark-secondary">
              <button onClick={() => void toggle(schedule)} className={`h-5 w-9 rounded-full p-0.5 transition-colors ${schedule.enabled ? 'bg-accent' : 'bg-surface-tertiary dark:bg-surface-dark-tertiary'}`} title={schedule.enabled ? 'Disable' : 'Enable'}><span className={`block h-4 w-4 rounded-full bg-white transition-transform ${schedule.enabled ? 'translate-x-4' : ''}`} /></button>
              <div className="min-w-0 flex-1"><h3 className="truncate text-xs font-semibold text-text-primary dark:text-text-dark-primary">{schedule.name}</h3><p className="mt-0.5 flex items-center gap-1 text-[10px] text-text-tertiary"><Clock3 className="h-3 w-3" />{cadenceLabel(schedule)} · Next {schedule.nextRunAt ? new Date(schedule.nextRunAt).toLocaleString() : 'not scheduled'}</p></div>
              <button disabled={busyId === schedule.id} onClick={() => void run(schedule)} className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-[10px] font-semibold text-text-secondary hover:text-accent dark:border-border-dark dark:text-text-dark-secondary"><Play className="h-3 w-3" /> Run now</button>
              <button onClick={() => void remove(schedule.id)} className="p-1.5 text-text-tertiary hover:text-red-500"><Trash2 className="h-3.5 w-3.5" /></button>
            </article>)}
            {!schedules.length && <div className="rounded-xl border border-dashed border-border p-10 text-center text-xs text-text-tertiary dark:border-border-dark">No scheduled skills yet.</div>}
          </div>
        </section>
        <section>
          <h2 className="mb-2 text-xs font-semibold text-text-primary dark:text-text-dark-primary">Recent runs</h2>
          <div className="overflow-hidden rounded-xl border border-border dark:border-border-dark">
            {runs.slice(0, 10).map(runItem => <div key={runItem.id} className="flex items-center gap-3 border-b border-border px-3 py-2.5 last:border-0 dark:border-border-dark"><span className="h-2 w-2 rounded-full bg-amber-500" /><span className="flex-1 truncate text-[11px] text-text-secondary dark:text-text-dark-secondary">{schedules.find(item => item.id === runItem.scheduleId)?.name ?? 'Scheduled skill'} · {runItem.triggeredBy}</span><span className="text-[10px] text-text-tertiary">{new Date(runItem.startedAt).toLocaleString()}</span><span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[9px] font-semibold uppercase text-amber-600">{runItem.status}</span></div>)}
            {!runs.length && <p className="p-5 text-center text-[11px] text-text-tertiary">Run history will appear here.</p>}
          </div>
        </section>
      </div>
    </div>
  </div>
}
