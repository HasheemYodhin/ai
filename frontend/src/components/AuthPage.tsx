import { useEffect, useState, type FormEvent } from 'react'
import { ChatsCircle, Code, FlowArrow, Eye, EyeSlash, WarningCircle } from '@phosphor-icons/react'
import { useAuth } from '@/hooks/useAuth'
import { cn } from '@/lib/utils'
import logo from '../icon.svg'

type Mode = 'login' | 'signup'

const EASE = 'ease-[cubic-bezier(0.22,1,0.36,1)]'

const HIGHLIGHTS = [
  { icon: ChatsCircle, title: 'Every model in one place', text: 'Chat with Claude, GPT, Gemini, NVIDIA and local models.' },
  { icon: Code, title: 'Write and run code', text: 'Generate code, preview artifacts and export documents.' },
  { icon: FlowArrow, title: 'Agents and automation', text: 'Projects, skills, connectors and scheduled tasks.' },
]

const MIN_PASSWORD = 10
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

interface AuthPageProps {
  initialMode?: Mode
  /** Keeps the URL (/login vs /signup) in step with the selected tab. */
  onModeChange?: (mode: Mode) => void
  /** Return to the landing page. */
  onHome?: () => void
}

/** Split screen sign in: brand panel on the left (md and up), form on the right. */
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

  const inputClass = cn(
    'w-full rounded-lg border border-border bg-surface px-3 py-2 body-3 text-text-primary outline-none',
    'placeholder:text-text-tertiary focus:border-accent dark:border-[#313131] dark:bg-[#181818] dark:text-text-dark-primary dark:placeholder:text-text-dark-tertiary',
    'transition-colors duration-300',
    EASE,
  )

  return (
    <div className="flex h-full overflow-y-auto bg-surface text-text-primary dark:bg-[#000000] dark:text-text-dark-primary">
      {/* Brand panel, hidden on phones so the form gets the full screen. */}
      <aside className="hidden flex-col justify-between border border-border bg-surface-secondary p-12 dark:border-[#272727] dark:bg-[#181818] md:flex md:w-5/12 lg:w-1/2 lg:p-16">
        <button type="button" onClick={onHome} className="flex items-center gap-2 self-start" aria-label="Dabba home">
          <img src={logo} alt="" className="h-8 w-8 object-contain" />
          <span className="title-2">Dabba</span>
        </button>

        <div className="max-w-md">
          <h2 className="heading-4 text-balance">Your AI workspace for chat, code and automation.</h2>
          <ul className="mt-10 space-y-6">
            {HIGHLIGHTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
                  <Icon size={20} aria-hidden="true" />
                </span>
                <div>
                  <p className="title-4">{title}</p>
                  <p className="body-6 mt-1 text-text-secondary dark:text-text-dark-secondary">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="caption-5 text-text-tertiary dark:text-text-dark-tertiary">
          Self hosted. Your chats stay on your Dabba server.
        </p>
      </aside>

      {/* Form panel */}
      <main id="main" className="flex flex-1 items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-sm">
          {/* Logo only on phones, where the brand panel is hidden. */}
          <button type="button" onClick={onHome} className="mb-8 flex items-center gap-2 md:hidden" aria-label="Dabba home">
            <img src={logo} alt="" className="h-8 w-8 object-contain" />
            <span className="title-2">Dabba</span>
          </button>

          <h1 className="heading-5">{isSignup ? 'Create your account' : 'Welcome back'}</h1>
          <p className="body-6 mt-2 text-text-secondary dark:text-text-dark-secondary">
            {isSignup ? 'Get started with Dabba in under a minute.' : 'Log in to continue to Dabba.'}
          </p>

          <div role="tablist" aria-label="Account" className="mt-8 grid grid-cols-2 rounded-xl bg-surface-tertiary p-1 dark:bg-[#272727]">
            {(['login', 'signup'] as const).map(tab => (
              <button
                key={tab}
                type="button"
                role="tab"
                aria-selected={mode === tab}
                onClick={() => switchMode(tab)}
                className={cn(
                  'rounded-lg py-2 button-sm transition-colors duration-300',
                  EASE,
                  mode === tab
                    ? 'bg-surface text-text-primary dark:bg-[#000000] dark:text-text-dark-primary'
                    : 'text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary',
                )}
              >
                {tab === 'login' ? 'Log in' : 'Sign up'}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-4">
            {isSignup && (
              <div className="space-y-2">
                <label htmlFor="auth-name" className="block title-4">Name</label>
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
              <label htmlFor="auth-email" className="block title-4">Email</label>
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
                className={cn(inputClass, emailInvalid && 'border-red-500 dark:border-red-500')}
              />
              {emailInvalid && (
                <p id="auth-email-error" className="caption-5 text-red-600 dark:text-red-400">Enter an email address like name@example.com.</p>
              )}
            </div>

            <div className="space-y-2">
              <label htmlFor="auth-password" className="block title-4">Password</label>
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
                  className={cn(inputClass, 'pr-12', passwordTooShort && 'border-amber-500 dark:border-amber-500')}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(v => !v)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                  className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary"
                >
                  {showPassword ? <EyeSlash size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {isSignup && (
                <p id="auth-password-hint" className={cn('caption-5', passwordTooShort ? 'text-amber-600 dark:text-amber-400' : 'text-text-tertiary dark:text-text-dark-tertiary')}>
                  {passwordTooShort
                    ? `${MIN_PASSWORD - password.length} more character${MIN_PASSWORD - password.length === 1 ? '' : 's'} needed`
                    : `Use at least ${MIN_PASSWORD} characters.`}
                </p>
              )}
            </div>

            {error && (
              <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2 body-6 text-red-600 dark:text-red-400">
                <WarningCircle size={18} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={busy || passwordTooShort}
              aria-busy={busy || undefined}
              className={cn(
                'flex w-full items-center justify-center rounded-lg bg-accent px-3 py-2 button-md text-white',
                'transition-[background-color,transform,opacity] duration-300 hover:bg-accent-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60',
                EASE,
              )}
            >
              {busy ? (isSignup ? 'Creating account…' : 'Logging in…') : (isSignup ? 'Create account' : 'Log in')}
            </button>
          </form>

          <p className="body-6 mt-6 text-center text-text-secondary dark:text-text-dark-secondary">
            {isSignup ? 'Already have an account? ' : "Don't have an account? "}
            <button type="button" onClick={() => switchMode(isSignup ? 'login' : 'signup')} className="body-4 text-accent hover:text-accent-hover">
              {isSignup ? 'Log in' : 'Sign up'}
            </button>
          </p>
        </div>
      </main>
    </div>
  )
}
