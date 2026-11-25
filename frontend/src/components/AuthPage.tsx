import { useEffect, useState, type FormEvent } from 'react'
import { CalendarCheck, Check, ChatsCircle, Eye, EyeSlash, WarningCircle } from '@phosphor-icons/react'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useAuth } from '@/hooks/useAuth'
import { cn } from '@/lib/utils'
import logo from '../icon.svg'

type Mode = 'login' | 'signup'

const MIN_PASSWORD = 10
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

// Same focus ring as the landing page.
const FOCUS = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--lp-ink)]'

interface AuthPageProps {
  initialMode?: Mode
  /** Keeps the URL (/login vs /signup) in step with the selected mode. */
  onModeChange?: (mode: Mode) => void
  /** Return to the app root. */
  onHome?: () => void
}

/**
 * Sign in / sign up in the landing page style: a centred white card floating
 * over the full-screen orange gradient, with the product cards drifting
 * around it (lg and up). No split panel.
 */
export function AuthPage({ initialMode = 'login', onModeChange, onHome }: AuthPageProps = {}) {
  const { signup, login } = useAuth()
  const [mode, setMode] = useState<Mode>(initialMode)
  // Follow Back/Forward between /login and /signup.
  useEffect(() => { setMode(initialMode) }, [initialMode])
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [emailTouched, setEmailTouched] = useState(false)
  const [busy, setBusy] = useState(false)

  const isSignup = mode === 'signup'
  const passwordTooShort = isSignup && password.length > 0 && password.length < MIN_PASSWORD
  // Client side email check, shown once the field has been left.
  const emailInvalid = emailTouched && email.trim().length > 0 && !EMAIL_PATTERN.test(email.trim())

  const switchMode = (next: Mode) => {
    setMode(next)
    setError(null)
    onModeChange?.(next)
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!EMAIL_PATTERN.test(email.trim())) {
      setEmailTouched(true)
      return
    }
    setBusy(true)
    try {
      if (isSignup) await signup(name, email, password)
      else await login(email, password)
    } catch (err) {
      setError((err as Error).message || 'That didn\'t work. Check your details and try again.')
    } finally {
      setBusy(false)
    }
  }

  const labelClass = 'block text-[13px] font-semibold text-[var(--lp-ink)]'
  const inputClass = cn(
    'w-full rounded-2xl border border-transparent bg-[var(--lp-soft)] px-4 py-3 text-[15px] text-[var(--lp-ink)] outline-none',
    'placeholder:text-[var(--lp-muted)] transition-colors duration-200 focus:border-[var(--lp-ink)] focus:bg-[var(--lp-card)]',
  )

  return (
    <div className="lp-theme relative h-full overflow-y-auto overflow-x-hidden bg-[radial-gradient(120%_90%_at_20%_10%,#ffd9c7_0%,#ff9a6b_38%,#ff5b23_70%,#c93b0c_100%)] font-sans text-[#141414] dark:bg-[radial-gradient(120%_90%_at_20%_10%,#6b3118_0%,#2e150a_45%,#0a0a0a_100%)]">
      <FloatingCards />

      <main id="main" className="relative z-10 flex min-h-full items-center justify-center px-3 py-6 sm:px-6">
        <div className="w-full max-w-[460px] rounded-[32px] bg-[var(--lp-card)] text-[var(--lp-ink)] p-7 shadow-[0_2px_4px_rgba(0,0,0,0.04),0_40px_80px_-24px_rgba(60,20,0,0.55)] sm:p-10">
          <header className="flex items-center justify-between gap-4">
            <button type="button" onClick={onHome} className={cn('flex items-center gap-2 rounded-full', FOCUS)} aria-label="Dabba home">
              <img src={logo} alt="" width={30} height={30} className="h-[30px] w-[30px] object-contain" />
              <span className="font-display text-[20px] font-semibold tracking-[-0.03em]">Dabba</span>
            </button>
            <div className="flex items-center gap-2">
              <ThemeToggle />
              <a href="/try" className={cn('rounded-md px-1 text-[14.5px] font-medium text-[var(--lp-ink-2)] hover:text-[var(--lp-ink)]', FOCUS)}>Try Dabba</a>
            </div>
          </header>

          <h1 className="mt-10 font-display text-[44px] font-semibold leading-none tracking-[-0.05em] sm:text-[52px]">
            {isSignup ? 'Create an account' : 'Log in'}
          </h1>
          <p className="mt-4 text-[15.5px] text-[var(--lp-muted)]">
            {isSignup ? 'Already have an account? ' : "Don't have an account? "}
            <button
              type="button"
              onClick={() => switchMode(isSignup ? 'login' : 'signup')}
              className={cn('rounded font-semibold text-[var(--lp-ink)] underline decoration-[var(--lp-dot)] underline-offset-4 hover:decoration-[var(--lp-ink)]', FOCUS)}
            >
              {isSignup ? 'Log in' : 'Create now'}
            </button>
          </p>

          <hr className="my-7 border-[var(--lp-line)]" />

          <form onSubmit={handleSubmit} noValidate className="space-y-5">
            {isSignup && (
              <div className="space-y-2">
                <label htmlFor="auth-name" className={labelClass}>Name</label>
                <input
                  id="auth-name"
                  autoFocus
                  required
                  autoComplete="name"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Your name"
                  className={inputClass}
                />
              </div>
            )}

            <div className="space-y-2">
              <label htmlFor="auth-email" className={labelClass}>Email</label>
              <input
                id="auth-email"
                type="email"
                required
                autoComplete="email"
                autoFocus={!isSignup}
                value={email}
                onChange={e => setEmail(e.target.value)}
                onBlur={() => setEmailTouched(true)}
                placeholder="you@example.com"
                aria-invalid={emailInvalid || undefined}
                aria-describedby={emailInvalid ? 'auth-email-error' : undefined}
                className={cn(inputClass, emailInvalid && 'border-red-600 focus:border-red-600')}
              />
              {emailInvalid && (
                <p id="auth-email-error" className="text-[13px] text-red-700">Enter an email address like name@example.com.</p>
              )}
            </div>

            <div className="space-y-2">
              <label htmlFor="auth-password" className={labelClass}>Password</label>
              <div className="relative">
                <input
                  id="auth-password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  minLength={isSignup ? MIN_PASSWORD : undefined}
                  autoComplete={isSignup ? 'new-password' : 'current-password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder={isSignup ? `At least ${MIN_PASSWORD} characters` : 'Your password'}
                  aria-describedby={isSignup ? 'auth-password-hint' : undefined}
                  aria-invalid={passwordTooShort || undefined}
                  className={cn(inputClass, 'pr-12', passwordTooShort && 'border-amber-600 focus:border-amber-600')}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(v => !v)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                  className={cn('absolute right-2 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full text-[var(--lp-muted)] hover:bg-[var(--lp-soft)] hover:text-[var(--lp-ink)]', FOCUS)}
                >
                  {showPassword ? <EyeSlash size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {isSignup && (
                <p id="auth-password-hint" className={cn('text-[13px]', passwordTooShort ? 'text-amber-800' : 'text-[var(--lp-muted)]')}>
                  {passwordTooShort
                    ? `${MIN_PASSWORD - password.length} more character${MIN_PASSWORD - password.length === 1 ? '' : 's'} needed`
                    : `Use at least ${MIN_PASSWORD} characters.`}
                </p>
              )}
            </div>

            {error && (
              <div role="alert" className="flex items-start gap-2 rounded-2xl border border-red-600/25 bg-red-50 px-4 py-3 text-[14px] text-red-800">
                <WarningCircle size={18} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={busy || passwordTooShort}
              aria-busy={busy || undefined}
              className={cn(
                'flex w-full items-center justify-center rounded-full bg-[var(--lp-btn)] px-6 py-3.5 text-[15px] font-semibold text-[var(--lp-btn-text)]',
                'shadow-[0_1px_0_rgba(255,255,255,0.15)_inset,0_8px_24px_-8px_rgba(20,20,20,0.45)] transition-[transform,opacity] duration-300 hover:-translate-y-0.5 active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0',
                FOCUS,
              )}
            >
              {busy ? (isSignup ? 'Creating account…' : 'Logging in…') : (isSignup ? 'Create account' : 'Log in')}
            </button>
          </form>

          <div className="my-6 flex items-center gap-3 text-[13px] text-[var(--lp-muted)]" aria-hidden="true">
            <span className="h-px flex-1 bg-[var(--lp-line)]" />or<span className="h-px flex-1 bg-[var(--lp-line)]" />
          </div>

          <a
            href="/try"
            className={cn('flex w-full items-center justify-center gap-2 rounded-full bg-[var(--lp-soft)] px-6 py-3.5 text-[15px] font-semibold text-[var(--lp-ink)] transition-colors hover:bg-[var(--lp-hover)]', FOCUS)}
          >
            <ChatsCircle size={18} className="text-[var(--lp-accent-text)]" aria-hidden="true" />
            Try Dabba without an account
          </a>

          <nav aria-label="Legal" className="mt-8 flex justify-center gap-5 text-[13px] text-[var(--lp-muted)]">
            <a href="/privacy" className={cn('rounded hover:text-[var(--lp-ink)] hover:underline', FOCUS)}>Privacy</a>
            <a href="/terms" className={cn('rounded hover:text-[var(--lp-ink)] hover:underline', FOCUS)}>Terms</a>
          </nav>
        </div>
      </main>
    </div>
  )
}

/** Decorative product cards around the login card (xl and up). Hidden from assistive tech. */
function FloatingCards() {
  return (
    <div aria-hidden="true" className="lp-light pointer-events-none absolute inset-0 hidden overflow-hidden xl:block">
      {/* Demo frame as a tilted window, left */}
      <div className="lp-rise absolute -left-10 top-[14%] w-[420px] -rotate-6" style={{ animationDelay: '100ms' }}>
        <div className="lp-float overflow-hidden rounded-[22px] border border-white/50 bg-white/30 p-2 shadow-[0_30px_60px_-20px_rgba(60,20,0,0.5)] backdrop-blur-sm">
          <img src="/demo/dabba-demo-poster.jpg" alt="" width={1280} height={720} className="aspect-video w-full rounded-[16px] object-cover object-left-top" />
        </div>
      </div>

      {/* Glass prompt chips, left */}
      <div className="lp-rise absolute bottom-[16%] left-[7%]" style={{ animationDelay: '300ms' }}>
        <div className="lp-float flex items-center gap-2.5 rounded-full border border-white/50 bg-white/70 py-2 pl-2 pr-4 text-[13.5px] font-medium shadow-[0_10px_30px_-12px_rgba(60,20,0,0.45)] backdrop-blur-md" style={{ animationDelay: '0.9s' }}>
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#FF5B23] text-[var(--lp-btn-text)]"><Check size={13} weight="bold" /></span>
          Explain this stack trace
        </div>
      </div>
      <div className="lp-rise absolute bottom-[9%] left-[14%]" style={{ animationDelay: '420ms' }}>
        <div className="lp-float flex items-center gap-2.5 rounded-full border border-white/50 bg-white/70 py-2 pl-2 pr-4 text-[13.5px] font-medium shadow-[0_10px_30px_-12px_rgba(60,20,0,0.45)] backdrop-blur-md" style={{ animationDelay: '1.6s' }}>
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#3b6cf6] text-[var(--lp-btn-text)]"><Check size={13} weight="bold" /></span>
          Draft the weekly status report
        </div>
      </div>

      {/* Stat card, top right */}
      <div className="lp-rise absolute right-[6%] top-[10%] w-[190px] rotate-3" style={{ animationDelay: '200ms' }}>
        <div className="lp-float rounded-[20px] bg-[var(--lp-card)] p-4 shadow-[0_2px_4px_rgba(0,0,0,0.04),0_18px_40px_-12px_rgba(60,20,0,0.35)]" style={{ animationDelay: '0.4s' }}>
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--lp-muted)]">— Choose from</p>
          <p className="mt-1 font-display text-[52px] font-semibold leading-none tracking-[-0.04em]">43</p>
          <p className="mt-2 text-[12.5px] leading-snug text-[var(--lp-muted)]">models from 8 providers. Switch any time.</p>
        </div>
      </div>

      {/* Scheduled task card, bottom right */}
      <div className="lp-rise absolute bottom-[14%] right-[5%] w-[280px] -rotate-3" style={{ animationDelay: '500ms' }}>
        <div className="lp-float flex items-center gap-3 rounded-[20px] bg-[var(--lp-card)] p-3 shadow-[0_2px_4px_rgba(0,0,0,0.04),0_18px_40px_-12px_rgba(60,20,0,0.35)]" style={{ animationDelay: '1.2s' }}>
          <span className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-[14px] bg-[var(--lp-soft)]">
            <CalendarCheck size={26} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[13.5px] font-medium leading-snug">Weekly status report<br /><span className="text-[var(--lp-muted)]">Mondays at 9:00</span></p>
            <div className="mt-1.5 flex items-center justify-between gap-2">
              <p className="text-[14px] font-bold">Scheduled</p>
              <span className="inline-flex items-center gap-1 rounded-full bg-[var(--lp-btn)] px-2 py-0.5 text-[11.5px] font-semibold text-[var(--lp-btn-text)]">
                <Check size={11} weight="bold" />
                Done
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
