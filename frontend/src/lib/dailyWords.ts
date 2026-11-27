export const WORD_LEVELS = ['Beginner', 'Intermediate', 'Advanced'] as const
export type WordLevel = (typeof WORD_LEVELS)[number]
export const WORD_COUNTS = [3, 5, 10] as const

export interface DailyWordsOptions {
  language: string
  level: WordLevel
  count: number
}

/**
 * Instructions for a "new words every day" schedule. The server adds today's
 * date and the earlier results to the prompt of each run, so the model can
 * avoid repeating words.
 */
export function dailyWordsInstructions({ language, level, count }: DailyWordsOptions): string {
  const lang = language.trim() || 'English'
  const article = /^[aeiou]/i.test(level) ? 'an' : 'a'
  const lines = [
    `Teach me ${count} new ${lang} vocabulary words today, at ${article} ${level.toLowerCase()} level.`,
    'For each word give:',
    '1. the word and its part of speech',
    lang.toLowerCase() === 'english' ? '2. a short, plain meaning' : '2. a short, plain meaning, in English as well',
    '3. one natural example sentence',
    '4. a quick tip to remember it',
    'Choose useful words from different topics. Never repeat a word that appears in an earlier result.',
    "Start with a one line greeting that mentions today's date, then the numbered list. Keep it short.",
  ]
  return lines.join('\n')
}
