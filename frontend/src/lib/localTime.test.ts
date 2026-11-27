import { afterEach, describe, expect, it } from 'vitest'
import { localTimeToUtc, utcTimeToLocal } from './localTime'

const originalTz = process.env.TZ
afterEach(() => { process.env.TZ = originalTz })

describe('local time <-> UTC for schedules', () => {
  it('converts India time (UTC+5:30) to UTC and back', () => {
    process.env.TZ = 'Asia/Kolkata'
    expect(localTimeToUtc('08:00')).toEqual({ time: '02:30', dayShift: 0 })
    expect(utcTimeToLocal('02:30')).toEqual({ time: '08:00', dayShift: 0 })
  })

  it('reports a day change when the conversion crosses midnight', () => {
    process.env.TZ = 'Asia/Kolkata'
    // 02:00 in India is 20:30 the previous day in UTC.
    expect(localTimeToUtc('02:00')).toEqual({ time: '20:30', dayShift: -1 })
    expect(utcTimeToLocal('20:30')).toEqual({ time: '02:00', dayShift: 1 })
  })

  it('leaves the time alone in UTC', () => {
    process.env.TZ = 'UTC'
    expect(localTimeToUtc('09:15')).toEqual({ time: '09:15', dayShift: 0 })
  })
})
