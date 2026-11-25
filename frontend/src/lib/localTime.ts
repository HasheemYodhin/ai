/**
 * The server runs schedules in UTC, while people think in their own time. These
 * convert a "HH:MM" time between the two. `dayShift` says whether the other
 * zone is on the previous (-1), same (0) or next (+1) calendar day, which
 * matters for weekly schedules. Uses today's offset, so a schedule saved
 * across a daylight saving change shifts by an hour in local time.
 */
export interface ShiftedTime {
  time: string
  dayShift: number
}

const pad = (n: number) => String(n).padStart(2, '0')

function parse(time: string): [number, number] {
  const [h, m] = time.split(':').map(Number)
  return [Number.isFinite(h) ? h : 9, Number.isFinite(m) ? m : 0]
}

/** A local "HH:MM" as the UTC time the server should use. */
export function localTimeToUtc(time: string): ShiftedTime {
  const [h, m] = parse(time)
  const now = new Date()
  const at = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m)
  const localDay = Date.UTC(at.getFullYear(), at.getMonth(), at.getDate())
  const utcDay = Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate())
  return { time: `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}`, dayShift: Math.round((utcDay - localDay) / 86_400_000) }
}

/** A server (UTC) "HH:MM" as the local time to show. */
export function utcTimeToLocal(time: string): ShiftedTime {
  const [h, m] = parse(time)
  const now = new Date()
  const at = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), h, m))
  const utcDay = Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate())
  const localDay = Date.UTC(at.getFullYear(), at.getMonth(), at.getDate())
  return { time: `${pad(at.getHours())}:${pad(at.getMinutes())}`, dayShift: Math.round((localDay - utcDay) / 86_400_000) }
}
