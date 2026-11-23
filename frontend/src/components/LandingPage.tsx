import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowRight, ArrowUpRight } from '@phosphor-icons/react'
import { cn } from '@/lib/utils'
import { setGuestPrefill } from '@/lib/guestPrefill'
import logo from '../icon.svg'

/**
 * Public landing page for signed out visitors at `/`, laid out like a
 * product announcement article: slim header, left aligned title with a
 * button pair, a narrow reading column with an "on this page" index,
 * sample prompt chips, a sample conversation, limitations, related cards
 * and a multi column footer.
 *
 * Visual rules from the landing page design system still apply (Geist,
 * named text styles, token spacing, flat backgrounds, one easing curve).
 * Every number comes from the codebase; nothing is invented.
 */

const EASE = 'ease-[cubic-bezier(0.22,1,0.36,1)]'

const SECTIONS = [
  { id: 'how-it-works', label: 'How it works' },
  { id: 'samples', label: 'Samples' },
  { id: 'limitations', label: 'Limitations' },
  { id: 'self-hosting', label: 'Self hosting' },
]

const SAMPLE_PROMPTS = [
  'Explain how HTTPS keeps data private, in simple terms',
  'Write a Python function that removes duplicates from a list',
  'Summarize the key points of a text I paste',
  'Plan a productive week with a simple daily schedule',
]

const LIMITATIONS = [
  'Dabba is only as good as the model you pick. Answers can still be wrong or out of date, so check anything important.',
  'The built in Dabba model is small and meant for experiments and casual chat. For real work, use a hosted model such as Claude, GPT, Gemini or NVIDIA.',
  'Hosted models need provider keys on your server, and you pay those providers for what you use.',
  'Features that run commands on the server, such as running code, Cowork, hooks and connectors, are limited to the workspace owner.',
]

const RELATED = [
  { image: '/landing/cowork.png', alt: 'Dabba Cowork task box', tag: 'Cowork', title: 'Hand off a whole task and get a report back' },
  { image: '/landing/connectors.png', alt: 'Dabba connectors catalogue', tag: 'Connectors', title: 'Bring GitHub, Drive, Slack and 57 more tools into the chat' },
  { image: '/landing/scheduled-skills.png', alt: 'Dabba scheduled skills page', tag: 'Automation', title: 'Run saved instructions on a schedule' },
]

const SAMPLE_REPLY_CODE = `def dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

print(dedupe([3, 1, 3, 2, 1]))  # [3, 1, 2]`

// ── Motion ───────────────────────────────────────────────────────────────

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Rises 32px and fades in once when it enters the viewport. */
function Reveal({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [shown, setShown] = useState(prefersReducedMotion)

  useEffect(() => {
    const el = ref.current
    if (!el || shown) return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setShown(true)
        observer.disconnect() // reveal once; never replay on scroll up
      }
    }, { rootMargin: '0px 0px -10% 0px' })
    observer.observe(el)
    return () => observer.disconnect()
  }, [shown])

  return (
    <div
      ref={ref}
      className={cn(
        'transition-[opacity,transform] duration-700 motion-reduce:transition-opacity',
        EASE,
        shown ? 'translate-y-0 opacity-100' : 'translate-y-8 opacity-0 motion-reduce:translate-y-0',
        className,
      )}
    >
      {children}
    </div>
  )
}

// ── Building blocks ──────────────────────────────────────────────────────

const primaryButton = cn(
  'inline-flex items-center justify-center gap-2 rounded-full bg-accent px-3 py-2 button-md text-white',
  'transition-[background-color,transform] duration-300 hover:bg-accent-hover active:scale-[0.98]',
  EASE,
)

const secondaryButton = cn(
  'inline-flex items-center justify-center gap-2 rounded-full border border-border px-3 py-2 button-md text-text-primary',
  'dark:border-[#313131] dark:text-text-dark-primary',
  'transition-[background-color,transform] duration-300 hover:bg-surface-tertiary active:scale-[0.98] dark:hover:bg-[#272727]',
  EASE,
)

function SectionTitle({ id, children }: { id: string; children: ReactNode }) {
  return <h2 id={id} className="heading-5 scroll-mt-24 text-balance">{children}</h2>
}

function Paragraph({ children }: { children: ReactNode }) {
  return <p className="body-3 text-pretty text-text-secondary dark:text-text-dark-secondary">{children}</p>
}

// ── Page ─────────────────────────────────────────────────────────────────

interface LandingPageProps {
  /** Opens the free guest chat at /try. */
  onTry: () => void
  onLogin: () => void
  onSignup: () => void
  onNavigate: (path: '/privacy' | '/terms') => void
}

export function LandingPage({ onTry, onLogin, onSignup, onNavigate }: LandingPageProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [currentSection, setCurrentSection] = useState<string>(SECTIONS[0].id)

  // Highlight the "on this page" entry for the section in view.
  useEffect(() => {
    const headings = SECTIONS.map(s => document.getElementById(s.id)).filter(Boolean) as HTMLElement[]
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) setCurrentSection(entry.target.id)
    }, { rootMargin: '0px 0px -70% 0px' })
    headings.forEach(h => observer.observe(h))
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!menuOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  /** A sample chip fills the guest chat's message box; the visitor still presses Send. */
  const trySample = (prompt: string) => {
    setGuestPrefill(prompt)
    onTry()
  }

  const footerColumns: { title: string; links: { label: string; onClick?: () => void; href?: string }[] }[] = [
    { title: 'Product', links: [{ label: 'Try Dabba', onClick: onTry }, { label: 'Create an account', onClick: onSignup }, { label: 'Log in', onClick: onLogin }] },
    { title: 'Learn', links: [{ label: 'How it works', href: '#how-it-works' }, { label: 'Samples', href: '#samples' }, { label: 'Limitations', href: '#limitations' }] },
    { title: 'Legal', links: [{ label: 'Privacy', onClick: () => onNavigate('/privacy') }, { label: 'Terms', onClick: () => onNavigate('/terms') }] },
  ]

  return (
    <div className="h-full overflow-y-auto bg-surface text-text-primary dark:bg-[#000000] dark:text-text-dark-primary">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-white">
        Skip to content
      </a>

      {/* Slim header */}
      <header className="sticky top-0 z-40 border-b border-border/60 bg-surface/80 backdrop-blur-md dark:border-[#272727] dark:bg-[#000000]/80">
        <nav aria-label="Main" className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <a href="/" aria-label="Dabba home" className="flex items-center gap-2">
            <img src={logo} alt="" className="h-6 w-6 object-contain" />
            <span className="title-3">Dabba</span>
          </a>
          <div className="hidden items-center gap-6 md:flex">
            {SECTIONS.map(s => (
              <a key={s.id} href={`#${s.id}`} className={cn('body-5 text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary transition-colors duration-300', EASE)}>
                {s.label}
              </a>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onLogin} className={cn('hidden rounded-full px-3 py-2 button-sm text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary transition-colors duration-300 sm:inline-flex', EASE)}>
              Log in
            </button>
            <button onClick={onTry} className={cn(primaryButton, 'button-sm')}>
              Try Dabba <ArrowUpRight size={16} weight="bold" aria-hidden="true" />
            </button>
            <button
              onClick={() => setMenuOpen(open => !open)}
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={menuOpen}
              aria-controls="mobile-menu"
              className="relative flex h-10 w-10 items-center justify-center rounded-lg md:hidden"
            >
              <span className={cn('absolute h-0.5 w-4 rounded-full bg-current transition-transform duration-500', EASE, menuOpen ? 'rotate-45' : '-translate-y-1')} />
              <span className={cn('absolute h-0.5 w-4 rounded-full bg-current transition-transform duration-500', EASE, menuOpen ? '-rotate-45' : 'translate-y-1')} />
            </button>
          </div>
        </nav>
      </header>

      {/* Mobile menu: full height panel; links rise in one after another. */}
      <div
        id="mobile-menu"
        aria-hidden={!menuOpen}
        className={cn(
          'fixed inset-x-0 bottom-0 top-16 z-30 flex flex-col bg-surface/95 px-6 pt-6 backdrop-blur-xl transition-opacity duration-500 dark:bg-[#000000]/95 md:hidden',
          EASE,
          menuOpen ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      >
        {[...SECTIONS.map(s => ({ key: s.id, label: s.label, href: `#${s.id}` })), { key: 'login', label: 'Log in', href: '' }].map((item, index) => {
          const style = { transitionDelay: menuOpen ? `${Math.min(index * 60, 400)}ms` : '0ms' }
          const className = cn(
            'border-b border-border py-4 text-left heading-6 transition-[opacity,transform] duration-500 dark:border-[#272727]',
            EASE,
            menuOpen ? 'translate-y-0 opacity-100' : 'translate-y-6 opacity-0',
          )
          return item.href ? (
            <a key={item.key} href={item.href} tabIndex={menuOpen ? 0 : -1} onClick={() => setMenuOpen(false)} style={style} className={className}>{item.label}</a>
          ) : (
            <button key={item.key} tabIndex={menuOpen ? 0 : -1} onClick={() => { setMenuOpen(false); onLogin() }} style={style} className={className}>{item.label}</button>
          )
        })}
      </div>

      <main id="main">
        {/* Title block */}
        <section className="mx-auto max-w-6xl px-4 pb-12 pt-16 sm:px-6 sm:pt-24">
          <div className="max-w-3xl">
            <p className="caption-4 text-text-secondary dark:text-text-dark-secondary">Dabba · Product</p>
            <h1 className="heading-3 sm:heading-2 mt-4 text-balance">
              Introducing Dabba, a self hosted AI workspace
            </h1>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <button onClick={onTry} className={primaryButton}>
                Try Dabba <ArrowUpRight size={18} weight="bold" aria-hidden="true" />
              </button>
              <button onClick={onSignup} className={secondaryButton}>
                Create an account
              </button>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 sm:px-6">
          <Reveal>
            <div className="overflow-hidden rounded-2xl border border-border bg-surface-secondary dark:border-[#272727] dark:bg-[#181818]">
              <img src="/landing/cowork.png" alt="The Dabba workspace with the chat sidebar and the Cowork task box" width={1440} height={900} className="block h-auto w-full" />
            </div>
          </Reveal>
        </section>

        {/* Article body with an "on this page" index on wide screens */}
        <div className="mx-auto grid max-w-6xl grid-cols-1 gap-12 px-4 py-16 sm:px-6 lg:grid-cols-4">
          <aside className="hidden lg:block">
            <nav aria-label="On this page" className="sticky top-24">
              <p className="caption-3 text-text-tertiary dark:text-text-dark-tertiary">On this page</p>
              <ul className="mt-3 space-y-1">
                {SECTIONS.map(s => (
                  <li key={s.id}>
                    <a
                      href={`#${s.id}`}
                      aria-current={currentSection === s.id ? 'location' : undefined}
                      className={cn(
                        'block rounded-lg px-2 py-1 body-6 transition-colors duration-300',
                        EASE,
                        currentSection === s.id
                          ? 'bg-surface-tertiary text-text-primary dark:bg-[#272727] dark:text-text-dark-primary'
                          : 'text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary',
                      )}
                    >
                      {s.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
          </aside>

          <article className="min-w-0 max-w-[680px] space-y-12 lg:col-span-3">
            <div className="space-y-4">
              <Paragraph>
                Dabba is an AI workspace you run on your own server. It puts models from Anthropic, OpenAI, Google, NVIDIA, Hugging Face and Ollama behind one chat, and adds the tools to get work done: agents that work through tasks, connectors to the apps you already use, saved skills, projects and scheduled automations.
              </Paragraph>
              <Paragraph>
                You can <button onClick={onTry} className="body-2 text-text-primary underline underline-offset-4 dark:text-text-dark-primary">try Dabba now</button> or create an account to pick your own models and keep your chats.
              </Paragraph>
            </div>

            {/* How it works */}
            <Reveal className="space-y-4">
              <SectionTitle id="how-it-works">How it works</SectionTitle>
              <Paragraph>
                One server runs the whole workspace. The web app, the terminal, the VS Code and Chrome extensions, and any OpenAI compatible client all talk to the same API. Behind it, an agent runtime plans and runs tasks, calls tools and connectors, and routes each request to the model you chose.
              </Paragraph>
              <div className="overflow-hidden rounded-2xl border border-border bg-surface-secondary dark:border-[#272727] dark:bg-[#181818]">
                <img src="/landing/architecture.png" alt="Dabba architecture: four clients, one API server, the platform and agent runtime, and the model and knowledge layer" loading="lazy" width={2400} height={1768} className="block h-auto w-full" />
              </div>
              <Paragraph>
                Today the model picker lists 43 models from 8 providers, and the connector catalogue offers 60 tools through MCP. Provider keys stay on the server and are never sent to the browser.
              </Paragraph>
            </Reveal>

            {/* Samples */}
            <Reveal className="space-y-4">
              <SectionTitle id="samples">Samples</SectionTitle>
              <Paragraph>Pick a prompt to open it in the free chat. It fills the message box; nothing is sent until you press Send.</Paragraph>
              <ul className="flex flex-wrap gap-2">
                {SAMPLE_PROMPTS.map(prompt => (
                  <li key={prompt}>
                    <button
                      onClick={() => trySample(prompt)}
                      className={cn('rounded-full border border-border px-3 py-2 body-6 text-text-secondary hover:bg-surface-tertiary hover:text-text-primary active:scale-[0.98] dark:border-[#313131] dark:text-text-dark-secondary dark:hover:bg-[#272727] dark:hover:text-text-dark-primary transition-[background-color,color,transform] duration-300', EASE)}
                    >
                      {prompt}
                    </button>
                  </li>
                ))}
              </ul>

              {/* A sample exchange, clearly labelled, showing the reply style. */}
              <figure className="mt-6 rounded-2xl border border-border p-6 dark:border-[#272727] dark:bg-[#181818]">
                <figcaption className="caption-3 text-text-tertiary dark:text-text-dark-tertiary">Sample conversation</figcaption>
                <div className="mt-4 space-y-4">
                  <div>
                    <p className="caption-3 text-text-secondary dark:text-text-dark-secondary">User</p>
                    <p className="body-3 mt-1">Write a Python function that removes duplicates from a list and keeps the order.</p>
                  </div>
                  <div>
                    <p className="caption-3 text-accent">Dabba</p>
                    <p className="body-3 mt-1 text-pretty">Here's a version that keeps the first time each item appears. A set makes each check fast.</p>
                    <pre className="mt-3 overflow-x-auto rounded-xl bg-surface-tertiary p-4 font-mono text-sm dark:bg-[#000000]"><code>{SAMPLE_REPLY_CODE}</code></pre>
                  </div>
                </div>
              </figure>
            </Reveal>

            {/* Limitations */}
            <Reveal className="space-y-4">
              <SectionTitle id="limitations">Limitations</SectionTitle>
              <ul className="list-disc space-y-3 pl-6 marker:text-text-tertiary">
                {LIMITATIONS.map(item => (
                  <li key={item} className="body-3 text-pretty text-text-secondary dark:text-text-dark-secondary">{item}</li>
                ))}
              </ul>
            </Reveal>

            {/* Self hosting */}
            <Reveal className="space-y-4">
              <SectionTitle id="self-hosting">Self hosting</SectionTitle>
              <Paragraph>
                Dabba is free to run on your own server. One Docker image serves the app and the API, with ready setups for Render, a Helm chart for Kubernetes, and an optional backup of the databases to Cloudflare R2 for hosts that wipe their disk.
              </Paragraph>
              <Paragraph>
                The first account created on a server becomes its owner. Later accounts are regular members.
              </Paragraph>
              <div className="flex flex-wrap gap-3 pt-2">
                <button onClick={onTry} className={primaryButton}>
                  Try Dabba <ArrowUpRight size={18} weight="bold" aria-hidden="true" />
                </button>
                <button onClick={onSignup} className={secondaryButton}>
                  Create an account
                </button>
              </div>
            </Reveal>

            <ul className="flex flex-wrap gap-2" aria-label="Topics">
              {['Dabba', 'Self hosted', 'Agents'].map(tag => (
                <li key={tag} className="rounded-full bg-surface-tertiary px-3 py-1 caption-4 text-text-secondary dark:bg-[#272727] dark:text-text-dark-secondary">{tag}</li>
              ))}
            </ul>
          </article>
        </div>

        {/* Explore more */}
        <section aria-labelledby="explore-title" className="border-t border-border dark:border-[#272727]">
          <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
            <div className="flex items-baseline justify-between gap-4">
              <h2 id="explore-title" className="heading-5">Explore Dabba</h2>
              <button onClick={onTry} className="body-5 text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary">
                Try it now
              </button>
            </div>
            <div className="mt-8 grid gap-6 md:grid-cols-3">
              {RELATED.map(card => (
                <button key={card.tag} onClick={onTry} className={cn('group flex flex-col items-stretch justify-start text-left', EASE)}>
                  <div className="overflow-hidden rounded-2xl border border-border bg-surface-secondary dark:border-[#272727] dark:bg-[#181818]">
                    <img src={card.image} alt={card.alt} loading="lazy" width={1440} height={900} className={cn('block aspect-[16/10] w-full object-cover object-top transition-transform duration-500 group-hover:scale-[1.02]', EASE)} />
                  </div>
                  <p className="caption-4 mt-4 text-text-tertiary dark:text-text-dark-tertiary">{card.tag}</p>
                  <p className="title-2 mt-1 text-balance">{card.title}</p>
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* Closing call to action */}
        <section className="border-t border-border dark:border-[#272727]">
          <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-6 px-4 py-16 sm:px-6 md:flex-row md:items-center">
            <h2 className="heading-5 sm:heading-4 max-w-[680px] text-balance">Start using Dabba today.</h2>
            <button onClick={onTry} className={primaryButton}>
              Try Dabba <ArrowRight size={18} weight="bold" aria-hidden="true" />
            </button>
          </div>
        </section>
      </main>

      {/* Multi column footer */}
      <footer className="border-t border-border dark:border-[#272727]">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
          <div className="grid grid-cols-2 gap-8 md:grid-cols-3">
            {footerColumns.map(column => (
              <div key={column.title}>
                <p className="title-4">{column.title}</p>
                <ul className="mt-3 space-y-2">
                  {column.links.map(link => (
                    <li key={link.label}>
                      {link.href ? (
                        <a
                          href={link.href}
                          {...(link.href.startsWith('http') ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
                          className="body-6 text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary"
                        >
                          {link.label}
                        </a>
                      ) : (
                        <button onClick={link.onClick} className="body-6 text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary">
                          {link.label}
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-12 flex flex-col items-start justify-between gap-4 border-t border-border pt-6 dark:border-[#272727] sm:flex-row sm:items-center">
            <span className="flex items-center gap-2 caption-2 text-text-secondary dark:text-text-dark-secondary">
              <img src={logo} alt="" className="h-5 w-5 object-contain" /> Dabba © {new Date().getFullYear()}
            </span>
          </div>
        </div>
      </footer>
    </div>
  )
}
