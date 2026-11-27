import { describe, expect, it } from 'vitest'
import { dailyWordsInstructions } from './dailyWords'

describe('daily words instructions', () => {
  it('asks for the chosen number of words, level and language', () => {
    const text = dailyWordsInstructions({ language: 'Spanish', level: 'Advanced', count: 10 })
    expect(text).toContain('10 new Spanish vocabulary words')
    expect(text).toContain('at an advanced level')
    expect(text).toContain('in English as well')
  })

  it('defaults to English and does not ask for a separate translation', () => {
    const text = dailyWordsInstructions({ language: '  ', level: 'Intermediate', count: 5 })
    expect(text).toContain('5 new English vocabulary words')
    expect(text).not.toContain('in English as well')
    expect(text).toContain('at an intermediate level')
    expect(dailyWordsInstructions({ language: 'English', level: 'Beginner', count: 3 })).toContain('at a beginner level')
  })

  it('tells the model not to repeat words from earlier results', () => {
    expect(dailyWordsInstructions({ language: 'English', level: 'Beginner', count: 3 })).toContain('Never repeat a word')
  })
})
