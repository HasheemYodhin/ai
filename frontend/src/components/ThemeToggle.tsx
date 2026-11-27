import { Moon, Sun } from '@phosphor-icons/react'
import { useTheme } from '@/hooks/useTheme'
import { cn } from '@/lib/utils'

/** Light/dark switch for the public pages. Colours come from the --lp-* theme variables. */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggleTheme } = useTheme()
  const dark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      className={cn(
        'flex h-9 w-9 items-center justify-center rounded-full text-[var(--lp-ink-2)] transition-colors hover:bg-[var(--lp-soft)] hover:text-[var(--lp-ink)]',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--lp-ink)]',
        className,
      )}
    >
      {dark ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
    </button>
  )
}
