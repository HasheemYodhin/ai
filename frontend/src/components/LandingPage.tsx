import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  ArrowRight, Briefcase, ChatsCircle, Plug, Key, HardDrives, UserCircleCheck, GithubLogo,
  Globe, TerminalWindow, Code, Browser, BracketsCurly,
} from '@phosphor-icons/react'
import { cn } from '@/lib/utils'
import logo from '../icon.svg'

/**
 * Public landing page for signed out visitors at `/`.
 *
 * Follows the landing page design system: Geist only, named text styles,
 * spacing from the token table, flat backgrounds (gradient only on the hero
 * heading text), Phosphor icons, and one easing curve for all motion.
 * Every number on the page comes from the codebase (model catalogue,
 * connector catalogue); nothing is invented.
 */

const SOURCE_URL = 'https://github.com/HasheemYodhin/ai'

/** Base motion curve: weighted, decelerating. Used for every transition. */
const EASE = 'ease-[cubic-bezier(0.22,1,0.36,1)]'

const NAV_LINKS = [
  { id: 'benefits', label: 'Benefits' },
  { id: 'how-it-works', label: 'How it works' },
  { id: 'faq', label: 'FAQ' },
]

const SURFACES = [
  { icon: Globe, label: 'Web app' },
  { icon: TerminalWindow, label: 'Terminal' },
  { icon: Code, label: 'VS Code' },
  { icon: Browser, label: 'Chrome' },
  { icon: BracketsCurly, label: 'OpenAI compatible API' },
]

const BENEFITS = [
  {
    icon: ChatsCircle,
    title: 'Switch models without switching apps',
    text: 'Pick from 43 models across 8 providers in one picker, and set how much reasoning each reply gets.',
    image: '/landing/agents.png',
    alt: 'Dabba model picker with Anthropic, OpenAI and Google models',
  },
  {
    icon: Briefcase,
    title: 'Hand off a whole task',
    text: 'Describe the result you need in Cowork, point it at a project folder, and Dabba works through it and reports back.',
    image: '/landing/cowork.png',
    alt: 'Dabba Cowork asking what it can take off your plate',
  },
  {
    icon: Plug,
    title: 'Bring your tools into the chat',
    text: 'Add GitHub, Google Drive, Microsoft 365, Slack, Jira, Notion and more from a catalogue of 60 connectors.',
    image: '/landing/connectors.png',
    alt: 'Dabba connectors catalogue',
  },
]

const STEPS = [
  { title: 'Deploy the Docker image', text: 'One image serves the app and the API. Use the included Render or Helm setup, or run it anywhere Docker runs.' },
  { title: 'Create the first account', text: 'The first person to sign up owns the workspace and can use every feature. Later accounts are regular members.' },
  { title: 'Add your provider keys', text: 'Set keys such as ANTHROPIC_API_KEY or NVIDIA_API_KEY as server environment variables, then pick a model and start.' },
]

const FACTS = [
  { value: '43', label: 'models in the picker' },
  { value: '8', label: 'model providers' },
  { value: '60', label: 'connectors in the catalogue' },
  { value: '5', label: 'ways to use it' },
]

const FAQS = [
  { q: 'What is Dabba?', a: 'A self hosted AI workspace. It combines chat across many models with agents, connectors, projects, saved skills and scheduled automations in one app.' },
  { q: 'How much does it cost?', a: 'Dabba is free to run on your own server, and the source is on GitHub. You pay your model providers directly for the API usage of the keys you add.' },
  { q: 'Which models can I use?', a: 'Models from Anthropic, OpenAI, Google, NVIDIA, Hugging Face and Ollama, plus local models. Each provider becomes available once its key is set on the server.' },
  { q: 'Where are my chats stored?', a: 'In SQLite databases on your Dabba server. Nothing is stored by a separate Dabba service.' },
  { q: 'Are my API keys exposed to the browser?', a: 'No. Keys are read from the server environment or stored encrypted on the server, and they are never sent to the browser.' },
  { q: 'Who can run code and commands?', a: 'Only the workspace owner, which is the first account created. Features that run commands on the server are locked for other accounts.' },
  { q: 'Where can I deploy it?', a: 'Anywhere Docker runs. The repository includes a Render blueprint, a Helm chart for Kubernetes, and an optional backup to Cloudflare R2 for hosts that wipe their disk.' },
]

// ── Motion helpers ───────────────────────────────────────────────────────

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
        shown ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8 motion-reduce:translate-y-0',
        className,
      )}
    >
      {children}
    </div>
  )
}

/**
 * Large tagline whose words move from a muted tone to full colour one at a
 * time as each crosses a trigger line 60% down the viewport.
 */
function TaglineReveal({ text }: { text: string }) {
  const words = text.split(' ')
  const containerRef = useRef<HTMLParagraphElement>(null)
  const [active, setActive] = useState<number>(() => (prefersReducedMotion() ? words.length : 0))

  useEffect(() => {
    const container = containerRef.current
    if (!container || active >= words.length) return
    const spans = Array.from(container.querySelectorAll<HTMLSpanElement>('[data-word]'))
    // One observer for all words; the negative bottom margin is the trigger line.
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const index = Number((entry.target as HTMLElement).dataset.word)
        // Keep reading order: a word lights up all words before it.
        setActive(current => Math.max(current, index + 1))
        observer.unobserve(entry.target)
      }
    }, { rootMargin: '0px 0px -40% 0px' })
    spans.forEach(span => observer.observe(span))
    return () => observer.disconnect()
  }, [active, words.length])

  return (
    <p ref={containerRef} className="heading-4 sm:heading-3 lg:heading-2 mx-auto max-w-[680px] text-balance text-center">
      {words.map((word, index) => (
        <span
          key={index}
          data-word={index}
          className={cn(
            'transition-opacity duration-500',
            EASE,
            index < active ? 'opacity-100' : 'opacity-30',
          )}
        >
          {word}{index < words.length - 1 ? ' ' : ''}
        </span>
      ))}
    </p>
  )
}

// ── Building blocks ──────────────────────────────────────────────────────

function PrimaryButton({ onClick, children, className }: { onClick: () => void; children: ReactNode; className?: string }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 button-md text-white',
        'transition-[background-color,transform] duration-300 hover:bg-accent-hover active:scale-[0.98]',
        EASE,
        className,
      )}
    >
      {children}
    </button>
  )
}

function Screenshot({ src, alt }: { src: string; alt: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface dark:border-[#272727] dark:bg-[#181818]">
      <img src={src} alt={alt} loading="lazy" width={1440} height={900} className="block h-auto w-full" />
    </div>
  )
}

function SectionHeading({ title, text }: { title: string; text?: string }) {
  return (
    <div className="mx-auto max-w-[680px] text-center">
      <h2 className="heading-4 sm:heading-3 text-balance">{title}</h2>
      {text && <p className="body-3 mt-4 text-pretty text-text-secondary dark:text-text-dark-secondary">{text}</p>}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────

interface LandingPageProps {
  onLogin: () => void
  onSignup: () => void
  onNavigate: (path: '/privacy' | '/terms') => void
}

export function LandingPage({ onLogin, onSignup, onNavigate }: LandingPageProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [currentSection, setCurrentSection] = useState<string | null>(null)

  // Highlight the nav link for the section currently in view.
  useEffect(() => {
    const sections = NAV_LINKS.map(link => document.getElementById(link.id)).filter(Boolean) as HTMLElement[]
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) setCurrentSection(entry.target.id)
    }, { rootMargin: '-45% 0px -50% 0px' })
    sections.forEach(section => observer.observe(section))
    return () => observer.disconnect()
  }, [])

  // The mobile menu covers the page; Escape closes it.
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  const linkClass = (id: string) => cn(
    'rounded-lg px-3 py-2 body-5 transition-colors duration-300',
    EASE,
    currentSection === id
      ? 'text-text-primary dark:text-text-dark-primary bg-surface-tertiary dark:bg-[#272727]'
      : 'text-text-secondary dark:text-text-dark-secondary hover:text-text-primary dark:hover:text-text-dark-primary',
  )

  return (
    <div className="h-full overflow-y-auto bg-surface text-text-primary dark:bg-[#000000] dark:text-text-dark-primary">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-white">
        Skip to content
      </a>

      {/* Floating navigation bar */}
      <header className="fixed inset-x-0 top-3 z-40 flex justify-center px-4">
        <nav aria-label="Main" className="flex w-full max-w-3xl items-center justify-between gap-4 rounded-2xl border border-border bg-surface/75 py-2 pl-4 pr-2 backdrop-blur-md dark:border-[#272727] dark:bg-[#181818]/75">
          <a href="/" aria-label="Dabba home" className="flex items-center gap-2">
            <img src={logo} alt="" className="h-6 w-6 object-contain" />
            <span className="title-3">Dabba</span>
          </a>
          <div className="hidden items-center gap-1 md:flex">
            {NAV_LINKS.map(link => (
              <a key={link.id} href={`#${link.id}`} aria-current={currentSection === link.id ? 'location' : undefined} className={linkClass(link.id)}>
                {link.label}
              </a>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <button onClick={onLogin} className={cn('hidden rounded-lg px-3 py-2 button-sm text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary transition-colors duration-300 sm:inline-flex', EASE)}>
              Log in
            </button>
            <PrimaryButton onClick={onSignup} className="button-sm">Get started</PrimaryButton>
            {/* Menu toggle: two lines that rotate into an X. */}
            <button
              onClick={() => setMenuOpen(open => !open)}
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={menuOpen}
              aria-controls="mobile-menu"
              className="relative ml-1 flex h-10 w-10 items-center justify-center rounded-lg md:hidden"
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
          'fixed inset-0 z-30 flex flex-col bg-surface/95 px-6 pt-24 backdrop-blur-xl transition-opacity duration-500 dark:bg-[#000000]/95 md:hidden',
          EASE,
          menuOpen ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      >
        {[...NAV_LINKS.map(link => ({ key: link.id, label: link.label, href: `#${link.id}` })), { key: 'login', label: 'Log in', href: '' }].map((item, index) => {
          const style = { transitionDelay: menuOpen ? `${Math.min(index * 60, 400)}ms` : '0ms' }
          const className = cn(
            'border-b border-border py-4 text-left heading-5 transition-[opacity,transform] duration-500 dark:border-[#272727]',
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
        {/* Hero */}
        <section className="px-4 pb-16 pt-32 sm:px-6 sm:pt-40">
          <div className="mx-auto flex max-w-[680px] flex-col items-center text-center">
            <h1 className="hero-heading-gradient heading-3 sm:heading-2 text-balance">
              One self hosted workspace <br className="hidden sm:block" />
              for every AI model you use
            </h1>
            <p className="body-3 mt-6 max-w-[680px] text-pretty text-text-secondary dark:text-text-dark-secondary">
              Dabba puts Claude, GPT, Gemini, NVIDIA and local models in one chat, with agents, connectors and scheduled skills, running on your own server.
            </p>
            <PrimaryButton onClick={onSignup} className="mt-8">
              Create your account <ArrowRight size={18} weight="bold" aria-hidden="true" />
            </PrimaryButton>
            <p className="caption-2 mt-4 text-text-tertiary dark:text-text-dark-tertiary">
              Works with Anthropic, OpenAI, Google, NVIDIA, Ollama and Hugging Face
            </p>
          </div>
          <Reveal className="mx-auto mt-16 max-w-5xl">
            <Screenshot src="/landing/cowork.png" alt="Dabba workspace with the sidebar and the Cowork task box" />
          </Reveal>
        </section>

        {/* Where you can use it */}
        <section aria-label="Where you can use Dabba" className="border-y border-border bg-surface-secondary px-4 py-6 dark:border-[#272727] dark:bg-[#181818]">
          <ul className="mx-auto flex max-w-5xl flex-wrap items-center justify-center gap-x-8 gap-y-3">
            {SURFACES.map(({ icon: Icon, label }) => (
              <li key={label} className="flex items-center gap-2 body-5 text-text-secondary dark:text-text-dark-secondary">
                <Icon size={18} aria-hidden="true" /> {label}
              </li>
            ))}
          </ul>
        </section>

        {/* Tagline reveal */}
        <section aria-label="Why Dabba" className="px-4 py-24 sm:px-6">
          <TaglineReveal text="Your models, your tools and your automations, in one app you run yourself." />
        </section>

        {/* Benefits */}
        <section id="benefits" className="scroll-mt-24 px-4 py-20 sm:px-6">
          <Reveal>
            <SectionHeading title="Everything you need in one place" text="Chat when you need an answer. Hand off the task when you need it done." />
          </Reveal>
          <div className="mx-auto mt-16 max-w-5xl space-y-20">
            {BENEFITS.map(({ icon: Icon, title, text, image, alt }, index) => (
              <Reveal key={title} className="grid items-center gap-8 lg:grid-cols-5 lg:gap-12">
                <div className={cn('lg:col-span-2', index % 2 && 'lg:order-2')}>
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent/10 text-accent">
                    <Icon size={20} aria-hidden="true" />
                  </span>
                  <h3 className="heading-5 mt-4 text-balance">{title}</h3>
                  <p className="body-3 mt-3 text-pretty text-text-secondary dark:text-text-dark-secondary">{text}</p>
                </div>
                <div className={cn('lg:col-span-3', index % 2 && 'lg:order-1')}>
                  <Screenshot src={image} alt={alt} />
                </div>
              </Reveal>
            ))}
            <Reveal className="grid gap-6 sm:grid-cols-2">
              {[
                { icon: Key, title: 'Keep keys on the server', text: 'Provider keys come from server environment variables or encrypted storage, and never reach the browser.' },
                { icon: HardDrives, title: 'Keep chats on your server', text: 'Accounts, chats and projects live in databases on your own Dabba server.' },
              ].map(({ icon: Icon, title, text }) => (
                <div key={title} className="rounded-2xl border border-border p-6 dark:border-[#272727] dark:bg-[#181818]">
                  <Icon size={22} className="text-accent" aria-hidden="true" />
                  <h3 className="title-2 mt-4">{title}</h3>
                  <p className="body-6 mt-2 text-pretty text-text-secondary dark:text-text-dark-secondary">{text}</p>
                </div>
              ))}
            </Reveal>
          </div>
        </section>

        {/* How it works */}
        <section id="how-it-works" className="scroll-mt-24 bg-surface-secondary px-4 py-20 dark:bg-[#181818] sm:px-6">
          <Reveal>
            <SectionHeading title="Running in three steps" />
          </Reveal>
          <Reveal className="mx-auto mt-12 grid max-w-5xl gap-6 md:grid-cols-3">
            {STEPS.map((step, index) => (
              <div key={step.title} className="rounded-2xl border border-border bg-surface p-6 dark:border-[#272727] dark:bg-[#000000]">
                <span className="caption-3 flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10 text-accent">{index + 1}</span>
                <h3 className="title-2 mt-4">{step.title}</h3>
                <p className="body-6 mt-2 text-pretty text-text-secondary dark:text-text-dark-secondary">{step.text}</p>
              </div>
            ))}
          </Reveal>
        </section>

        {/* Product facts (proof) */}
        <section aria-label="Dabba in numbers" className="px-4 py-20 sm:px-6">
          <Reveal className="mx-auto grid max-w-5xl grid-cols-2 gap-6 md:grid-cols-4">
            {FACTS.map(fact => (
              <div key={fact.label} className="text-center">
                <p className="heading-3">{fact.value}</p>
                <p className="caption-2 mt-2 text-text-secondary dark:text-text-dark-secondary">{fact.label}</p>
              </div>
            ))}
          </Reveal>
        </section>

        {/* FAQ */}
        <section id="faq" className="scroll-mt-24 px-4 pb-20 sm:px-6">
          <Reveal>
            <SectionHeading title="Questions and answers" />
          </Reveal>
          <Reveal className="mx-auto mt-12 max-w-[680px] space-y-3">
            {FAQS.map(item => (
              <details key={item.q} className="group rounded-xl border border-border px-4 py-3 dark:border-[#272727] dark:bg-[#181818]">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 title-3 [&::-webkit-details-marker]:hidden">
                  {item.q}
                  <span aria-hidden="true" className={cn('text-text-tertiary transition-transform duration-300 group-open:rotate-45 dark:text-text-dark-tertiary', EASE)}>+</span>
                </summary>
                <p className="body-6 mt-3 text-pretty text-text-secondary dark:text-text-dark-secondary">{item.a}</p>
              </details>
            ))}
          </Reveal>
        </section>

        {/* Risk reversal + final CTA */}
        <section className="px-4 pb-24 sm:px-6">
          <Reveal className="mx-auto max-w-5xl rounded-3xl border border-border bg-surface-secondary px-6 py-16 text-center dark:border-[#272727] dark:bg-[#181818] sm:px-12">
            <UserCircleCheck size={28} className="mx-auto text-accent" aria-hidden="true" />
            <h2 className="heading-4 sm:heading-3 mx-auto mt-4 max-w-[680px] text-balance">Free to self host, with the source on GitHub</h2>
            <p className="body-3 mx-auto mt-4 max-w-[680px] text-pretty text-text-secondary dark:text-text-dark-secondary">
              Run it on your own server at no cost. You only pay your model providers for the keys you add.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <PrimaryButton onClick={onSignup}>
                Create your account <ArrowRight size={18} weight="bold" aria-hidden="true" />
              </PrimaryButton>
              <a href={SOURCE_URL} target="_blank" rel="noopener noreferrer" className={cn('inline-flex items-center gap-2 rounded-lg px-3 py-2 button-md text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary transition-colors duration-300', EASE)}>
                <GithubLogo size={18} aria-hidden="true" /> View the source
              </a>
            </div>
          </Reveal>
        </section>
      </main>

      <footer className="border-t border-border px-4 py-8 dark:border-[#272727] sm:px-6">
        <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-4 sm:flex-row">
          <span className="flex items-center gap-2 caption-2 text-text-secondary dark:text-text-dark-secondary">
            <img src={logo} alt="" className="h-5 w-5 object-contain" /> © {new Date().getFullYear()} Dabba
          </span>
          <nav aria-label="Footer" className="flex items-center gap-6 caption-2 text-text-secondary dark:text-text-dark-secondary">
            <button onClick={() => onNavigate('/privacy')} className="hover:text-text-primary dark:hover:text-text-dark-primary">Privacy</button>
            <button onClick={() => onNavigate('/terms')} className="hover:text-text-primary dark:hover:text-text-dark-primary">Terms</button>
            <a href={SOURCE_URL} target="_blank" rel="noopener noreferrer" className="hover:text-text-primary dark:hover:text-text-dark-primary">GitHub</a>
          </nav>
        </div>
      </footer>
    </div>
  )
}
