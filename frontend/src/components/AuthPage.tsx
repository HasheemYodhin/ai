import { useEffect, useState, type FormEvent } from 'react'
import { Eye, EyeOff, Loader2, MessagesSquare, Code2, Workflow, AlertCircle } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { cn } from '@/lib/utils'
import logo from '../icon.svg'

type Mode = 'login' | 'signup'

const HIGHLIGHTS = [
  { icon: MessagesSquare, title: 'Every model in one place', text: 'Chat with Claude, GPT, Gemini, NVIDIA and local models.' },
  { icon: Code2, title: 'Write and run code', text: 'Generate code, preview artifacts and export documents.' },
  { icon: Workflow, title: 'Agents and automation', text: 'Projects, skills, connectors and scheduled tasks.' },
]

const MIN_PASSWORD = 10

interface AuthPageProps {
  initialMode?: Mode
  /** Keeps the URL (/login vs /signup) in step with the selected tab. */
  onModeChange?: (mode: Mode) => void
  /** Return to the landing page. */
  onHome?: () => void
}

/** Split-screen sign-in: brand panel on the left (md and up), form on the right. */
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
  const [busy, setBusy] = useState(false)

  const isSignup = mode === 'signup'
  const passwordTooShort = isSignup && password.length > 0 && password.length < MIN_PASSWORD

  const switchMode = (next: Mode) => {
    setMode(next)
    setError(null)
    onModeChange?.(next)
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (isSignup) await signup(name, email, password)
      else await login(email, password)
    } catch (err) {
      setError((err as Error).message || 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const inputClass = 'w-full h-11 px-3.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/60 focus:ring-2 focus:ring-accent/15 transition-colors'

  return (
    <div className="flex h-full overflow-y-auto bg-surface dark:bg-surface-dark">
      {/* Brand panel — hidden on phones so the form gets the full screen. */}
      <aside className="relative hidden md:flex md:w-[44%] lg:w-[48%] flex-col justify-between overflow-hidden bg-surface-secondary dark:bg-surface-dark-secondary border-r border-border dark:border-border-dark p-10 lg:p-14">
        <button type="button" onClick={onHome} className="flex items-center gap-2.5 self-start" aria-label="Dabba home">
          <img src={logo} alt="" className="w-9 h-9 object-contain" />
          <span className="text-lg font-semibold text-text-primary dark:text-text-dark-primary">Dabba</span>
        </button>

        <div className="max-w-md">
          <h2 className="text-3xl lg:text-[34px] leading-tight font-semibold tracking-tight text-text-primary dark:text-text-dark-primary">
            Your AI workspace for chat, code and automation.
          </h2>
          <ul className="mt-10 space-y-6">
            {HIGHLIGHTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3.5">
                <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
                  <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-text-primary dark:text-text-dark-primary">{title}</p>
                  <p className="mt-0.5 text-sm text-text-secondary dark:text-text-dark-secondary">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-text-tertiary dark:text-text-dark-tertiary">
          Self-hosted. Your chats stay on your Dabba server.
        </p>
      </aside>

      {/* Form panel */}
      <main className="flex flex-1 items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-[380px]">
          {/* Logo only on phones, where the brand panel is hidden. */}
          <button type="button" onClick={onHome} className="mb-8 flex items-center gap-2.5 md:hidden" aria-label="Dabba home">
            <img src={logo} alt="" className="w-8 h-8 object-contain" />
            <span className="text-lg font-semibold text-text-primary dark:text-text-dark-primary">Dabba</span>
          </button>

          <h1 className="text-2xl font-semibold tracking-tight text-text-primary dark:text-text-dark-primary">
            {isSignup ? 'Create your account' : 'Welcome back'}
          </h1>
          <p className="mt-1.5 text-sm text-text-secondary dark:text-text-dark-secondary">
            {isSignup ? 'Get started with Dabba in under a minute.' : 'Log in to continue to Dabba.'}
          </p>

          <div role="tablist" aria-label="Account" className="mt-7 grid grid-cols-2 rounded-xl bg-surface-tertiary dark:bg-surface-dark-tertiary p-1">
            {(['login', 'signup'] as const).map(tab => (
              <button
                key={tab}
                type="button"
                role="tab"
                aria-selected={mode === tab}
                onClick={() => switchMode(tab)}
                className={cn(
                  'h-9 rounded-lg text-sm font-medium transition-colors',
                  mode === tab
                    ? 'bg-surface dark:bg-surface-dark-secondary text-text-primary dark:text-text-dark-primary shadow-sm'
                    : 'text-text-secondary dark:text-text-dark-secondary hover:text-text-primary dark:hover:text-text-dark-primary'
                )}
              >
                {tab === 'login' ? 'Log in' : 'Sign up'}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            {isSignup && (
              <div className="space-y-1.5">
                <label htmlFor="auth-name" className="block text-sm font-medium text-text-primary dark:text-text-dark-primary">Name</label>
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

            <div className="space-y-1.5">
              <label htmlFor="auth-email" className="block text-sm font-medium text-text-primary dark:text-text-dark-primary">Email</label>
              <input
                id="auth-email"
                type="email"
                required
                autoComplete="email"
                autoFocus={!isSignup}
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                className={inputClass}
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="auth-password" className="block text-sm font-medium text-text-primary dark:text-text-dark-primary">Password</label>
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
                  className={cn(inputClass, 'pr-11', passwordTooShort && 'border-amber-500/60')}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(v => !v)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                  className="absolute right-2 top-1/2 -translate-y-1/2 flex h-8 w-8 items-center justify-center rounded-lg text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary transition-colors"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {isSignup && (
                <p id="auth-password-hint" className={cn('text-xs', passwordTooShort ? 'text-amber-600 dark:text-amber-400' : 'text-text-tertiary dark:text-text-dark-tertiary')}>
                  {passwordTooShort
                    ? `${MIN_PASSWORD - password.length} more character${MIN_PASSWORD - password.length === 1 ? '' : 's'} needed`
                    : `Use at least ${MIN_PASSWORD} characters.`}
                </p>
              )}
            </div>

            {error && (
              <div role="alert" className="flex items-start gap-2 rounded-xl border border-red-500/20 bg-red-500/5 px-3 py-2.5 text-sm text-red-600 dark:text-red-400">
                <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden="true" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={busy || passwordTooShort}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-accent hover:bg-accent-hover disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors"
            >
              {busy && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
              {busy ? (isSignup ? 'Creating account…' : 'Logging in…') : (isSignup ? 'Create account' : 'Log in')}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-text-secondary dark:text-text-dark-secondary">
            {isSignup ? 'Already have an account? ' : "Don't have an account? "}
            <button
              type="button"
              onClick={() => switchMode(isSignup ? 'login' : 'signup')}
              className="font-semibold text-accent hover:text-accent-hover"
            >
              {isSignup ? 'Log in' : 'Sign up'}
            </button>
          </p>
        </div>
      </main>
    </div>
  )
}
