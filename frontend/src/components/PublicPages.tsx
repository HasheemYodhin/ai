import { ArrowLeft } from '@phosphor-icons/react'
import logo from '../icon.svg'

/** Shared shell for small public pages (legal, not found): logo, content, way back. */
function PublicShell({ onHome, children }: { onHome: () => void; children: React.ReactNode }) {
  return (
    <div className="h-full overflow-y-auto bg-surface text-text-primary dark:bg-[#000000] dark:text-text-dark-primary">
      <header className="px-4 py-6 sm:px-6">
        <button onClick={onHome} aria-label="Dabba home" className="mx-auto flex max-w-[680px] items-center gap-2">
          <img src={logo} alt="" className="h-6 w-6 object-contain" />
          <span className="title-3">Dabba</span>
        </button>
      </header>
      <main id="main" className="px-4 pb-24 pt-12 sm:px-6">
        <div className="mx-auto max-w-[680px]">{children}</div>
      </main>
    </div>
  )
}

function BackHome({ onHome, label = 'Back to home' }: { onHome: () => void; label?: string }) {
  return (
    <button
      onClick={onHome}
      className="mt-8 inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 button-md text-white transition-[background-color,transform] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] hover:bg-accent-hover active:scale-[0.98]"
    >
      <ArrowLeft size={18} weight="bold" aria-hidden="true" /> {label}
    </button>
  )
}

/**
 * Privacy and terms. The wording must come from the owner's legal counsel, so
 * the body is a clearly marked placeholder until it's provided.
 */
export function LegalPage({ kind, onHome }: { kind: 'privacy' | 'terms'; onHome: () => void }) {
  const title = kind === 'privacy' ? 'Privacy policy' : 'Terms of use'
  return (
    <PublicShell onHome={onHome}>
      <h1 className="heading-4 sm:heading-3 text-balance">{title}</h1>
      <p className="body-3 mt-6 text-pretty text-text-secondary dark:text-text-dark-secondary">
        {kind === 'privacy' ? '{{privacy_policy}}' : '{{terms_of_use}}'}
      </p>
      <BackHome onHome={onHome} />
    </PublicShell>
  )
}

/** Branded 404 for unknown public addresses. */
export function NotFoundPage({ onHome }: { onHome: () => void }) {
  return (
    <PublicShell onHome={onHome}>
      <p className="caption-3 text-accent">404</p>
      <h1 className="heading-4 sm:heading-3 mt-2 text-balance">This page doesn't exist</h1>
      <p className="body-3 mt-4 text-pretty text-text-secondary dark:text-text-dark-secondary">
        The address may be mistyped, or the page may have moved. Head back to the home page to keep going.
      </p>
      <BackHome onHome={onHome} label="Go to the home page" />
    </PublicShell>
  )
}
