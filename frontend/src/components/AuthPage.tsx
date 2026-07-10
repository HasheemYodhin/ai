import { useState, type FormEvent } from 'react'
import { Sparkles, Eye, EyeOff, Loader2 } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import logo from '../icon.svg'

export function AuthPage() {
  const { signup, login } = useAuth()
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (mode === 'signup') {
        await signup(name, email, password)
      } else {
        await login(email, password)
      }
    } catch (err) {
      setError((err as Error).message || 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center justify-center h-full bg-surface-secondary dark:bg-surface-dark px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <img src={logo} alt="Dabba Logo" className="w-12 h-12 object-contain rounded-xl mb-3" />
          <h1 className="text-xl font-bold text-text-primary dark:text-text-dark-primary">Dabba</h1>
          <p className="text-sm text-text-secondary dark:text-text-dark-secondary mt-1">
            {mode === 'login' ? 'Welcome back' : 'Create your account'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3.5 bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark rounded-2xl p-6 shadow-sm">
          {mode === 'signup' && (
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Name</label>
              <input
                autoFocus
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Your name"
                className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
              />
            </div>
          )}

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Email</label>
            <input
              type="email"
              autoFocus={mode === 'login'}
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full px-3.5 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary dark:text-text-dark-secondary">Password</label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder={mode === 'signup' ? 'At least 6 characters' : '••••••••'}
                className="w-full px-3.5 pr-10 py-2.5 text-sm rounded-xl glass-input border border-border dark:border-border-dark outline-none focus:border-accent/40 transition-colors"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-text-secondary hover:text-text-primary rounded-lg transition-colors"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-accent hover:bg-accent-hover disabled:opacity-60 text-white text-sm font-semibold transition-colors"
          >
            {busy && <Loader2 className="w-4 h-4 animate-spin" />}
            {mode === 'login' ? 'Log in' : 'Sign up'}
          </button>

          <p className="text-center text-xs text-text-tertiary dark:text-text-dark-tertiary pt-1">
            {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
            <button
              type="button"
              onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setError(null) }}
              className="text-accent font-semibold hover:text-accent-hover"
            >
              {mode === 'login' ? 'Sign up' : 'Log in'}
            </button>
          </p>
        </form>

        <p className="text-center text-[10px] text-text-tertiary dark:text-text-dark-tertiary mt-4">
          Your profile is stored only in this browser — there's no server-side account system.
        </p>
      </div>
    </div>
  )
}
