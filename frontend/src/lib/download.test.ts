import { describe, expect, it } from 'vitest'
import { firstCodeBlock, safeFileName } from './download'

describe('download helpers', () => {
  it('creates safe bounded file names', () => {
    expect(safeFileName(' Quarterly Results / 2026 ', 'pdf')).toBe('quarterly-results-2026.pdf')
  })

  it('extracts fenced source code without the fence', () => {
    expect(firstCodeBlock('Before\n```python\nprint("ok")\n```\nAfter')).toEqual({
      lang: 'python',
      code: 'print("ok")',
    })
  })
})
