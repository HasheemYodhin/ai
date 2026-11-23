import {
  ArrowRight, MessagesSquare, Code2, BriefcaseBusiness, Plug, FolderKanban, CalendarClock,
  Globe, Terminal, SquareCode, Braces, Server, KeyRound, ShieldCheck,
} from 'lucide-react'
import logo from '../icon.svg'

/**
 * Public front page for signed-out visitors at `/`. Everything here describes
 * features Dabba actually ships; screenshots live in public/landing/.
 */
interface LandingPageProps {
  onLogin: () => void
  onSignup: () => void
}

const FEATURES = [
  { icon: MessagesSquare, title: 'Every model in one place', text: 'Switch between Claude, GPT, Gemini, NVIDIA, Ollama and local models from the same chat, with a reasoning-effort control for each.' },
  { icon: Code2, title: 'Write and run code', text: 'Syntax-highlighted code, live artifact previews, and exports to PDF, Word, Excel and PowerPoint.' },
  { icon: BriefcaseBusiness, title: 'Cowork', text: 'Describe the result you need, point it at a project folder, and let Dabba work through the task and report back.' },
  { icon: Plug, title: 'Connectors', text: 'Bring in GitHub, Google Drive, Microsoft 365, Slack, Jira, Notion and more through MCP.' },
  { icon: FolderKanban, title: 'Projects and skills', text: 'Group chats with shared instructions, and save reusable prompts that apply automatically.' },
  { icon: CalendarClock, title: 'Scheduled skills and hooks', text: 'Run instructions on a schedule with run history, and trigger shell hooks on agent events.' },
]

const SURFACES = [
  { icon: Globe, label: 'Web app' },
  { icon: Terminal, label: 'Terminal' },
  { icon: SquareCode, label: 'VS Code' },
  { icon: Globe, label: 'Chrome' },
  { icon: Braces, label: 'OpenAI-compatible API' },
]

const SHOWCASE = [
  {
    image: '/landing/agents.png',
    alt: 'Dabba model picker grouped by provider',
    eyebrow: 'Models',
    title: 'Pick the right model for each job',
    text: 'Models are grouped by provider with their reasoning tier. Add a provider key once on the server and every model from that provider is ready to use.',
  },
  {
    image: '/landing/connectors.png',
    alt: 'Dabba connectors catalogue',
    eyebrow: 'Connectors',
    title: 'Work across the tools you already use',
    text: 'Install connectors from the catalogue and use their tools from any chat, or hand a whole task to Cowork.',
  },
  {
    image: '/landing/scheduled-skills.png',
    alt: 'Dabba scheduled skills page',
    eyebrow: 'Automation',
    title: 'Let routine work run on its own',
    text: 'Schedule a skill daily or on an interval, and check its run history when you want to see what happened.',
  },
]

/** A screenshot in a simple window frame. */
function Screenshot({ src, alt }: { src: string; alt: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border dark:border-border-dark bg-surface dark:bg-surface-dark-secondary shadow-[0_24px_60px_-30px_rgba(0,0,0,0.35)]">
      <div className="flex items-center gap-1.5 border-b border-border dark:border-border-dark px-3.5 py-2.5" aria-hidden="true">
        <span className="h-2.5 w-2.5 rounded-full bg-border dark:bg-border-dark" />
        <span className="h-2.5 w-2.5 rounded-full bg-border dark:bg-border-dark" />
        <span className="h-2.5 w-2.5 rounded-full bg-border dark:bg-border-dark" />
      </div>
      <img src={src} alt={alt} loading="lazy" width={1440} height={900} className="block h-auto w-full" />
    </div>
  )
}

export function LandingPage({ onLogin, onSignup }: LandingPageProps) {
  return (
    <div className="h-full overflow-y-auto bg-surface dark:bg-surface-dark text-text-primary dark:text-text-dark-primary">
      {/* Nav */}
      <header className="sticky top-0 z-20 border-b border-border/70 dark:border-border-dark/70 bg-surface/90 dark:bg-surface-dark/90 backdrop-blur">
        <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6" aria-label="Main">
          <a href="/" className="flex items-center gap-2.5" aria-label="Dabba home">
            <img src={logo} alt="" className="h-8 w-8 object-contain" />
            <span className="text-[17px] font-semibold">Dabba</span>
          </a>
          <div className="hidden items-center gap-7 text-sm text-text-secondary dark:text-text-dark-secondary md:flex">
            <a href="#features" className="hover:text-text-primary dark:hover:text-text-dark-primary">Features</a>
            <a href="#tour" className="hover:text-text-primary dark:hover:text-text-dark-primary">Tour</a>
            <a href="#self-hosted" className="hover:text-text-primary dark:hover:text-text-dark-primary">Self-hosted</a>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onLogin} className="h-9 rounded-lg px-3.5 text-sm font-medium text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors">
              Log in
            </button>
            <button onClick={onSignup} className="h-9 rounded-lg bg-accent px-3.5 text-sm font-semibold text-white hover:bg-accent-hover transition-colors">
              Get started
            </button>
          </div>
        </nav>
      </header>

      <main>
        {/* Hero */}
        <section className="mx-auto max-w-6xl px-4 pb-16 pt-16 sm:px-6 sm:pt-24">
          <div className="mx-auto max-w-3xl text-center">
            <h1 className="text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl lg:text-[56px]">
              Your AI workspace for chat, code and automation
            </h1>
            <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-text-secondary dark:text-text-dark-secondary sm:text-lg">
              Dabba brings the major AI models, your tools and your automations into one app that runs on your own server.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <button onClick={onSignup} className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-accent px-5 text-sm font-semibold text-white hover:bg-accent-hover transition-colors sm:w-auto">
                Create your account <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </button>
              <button onClick={onLogin} className="inline-flex h-11 w-full items-center justify-center rounded-xl border border-border dark:border-border-dark px-5 text-sm font-semibold hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors sm:w-auto">
                Log in
              </button>
            </div>
          </div>
          <div className="mx-auto mt-14 max-w-5xl">
            <Screenshot src="/landing/cowork.png" alt="Dabba Cowork workspace asking what it can take off your plate" />
          </div>
        </section>

        {/* Surfaces */}
        <section aria-label="Where you can use Dabba" className="border-y border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-secondary">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-8 gap-y-3 px-4 py-6 text-sm text-text-secondary dark:text-text-dark-secondary sm:px-6">
            <span className="font-medium text-text-primary dark:text-text-dark-primary">Use it from</span>
            {SURFACES.map(({ icon: Icon, label }) => (
              <span key={label} className="inline-flex items-center gap-2">
                <Icon className="h-4 w-4" aria-hidden="true" /> {label}
              </span>
            ))}
          </div>
        </section>

        {/* Features */}
        <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <div className="max-w-2xl">
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">Everything in one workspace</h2>
            <p className="mt-3 text-text-secondary dark:text-text-dark-secondary">
              Chat when you need an answer, hand off a task when you need it done.
            </p>
          </div>
          <div className="mt-12 grid gap-x-10 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <div key={title}>
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent/10 text-accent">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <h3 className="mt-4 text-base font-semibold">{title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-text-secondary dark:text-text-dark-secondary">{text}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Tour */}
        <section id="tour" className="scroll-mt-20 bg-surface-secondary dark:bg-surface-dark-secondary">
          <div className="mx-auto max-w-6xl space-y-20 px-4 py-20 sm:px-6">
            {SHOWCASE.map((item, index) => (
              <div key={item.title} className="grid items-center gap-8 lg:grid-cols-5 lg:gap-12">
                <div className={index % 2 ? 'lg:order-2 lg:col-span-2' : 'lg:col-span-2'}>
                  <p className="text-sm font-semibold text-accent">{item.eyebrow}</p>
                  <h3 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{item.title}</h3>
                  <p className="mt-3 leading-relaxed text-text-secondary dark:text-text-dark-secondary">{item.text}</p>
                </div>
                <div className={index % 2 ? 'lg:order-1 lg:col-span-3' : 'lg:col-span-3'}>
                  <Screenshot src={item.image} alt={item.alt} />
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Self-hosted */}
        <section id="self-hosted" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <div className="max-w-2xl">
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">Runs on your server</h2>
            <p className="mt-3 text-text-secondary dark:text-text-dark-secondary">
              Deploy Dabba where you want it and keep control of your data and keys.
            </p>
          </div>
          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {[
              { icon: Server, title: 'Deploy anywhere', text: 'One Docker image serves the app and the API. Ready-made setups for Render and Kubernetes (Helm).' },
              { icon: KeyRound, title: 'Keys stay server-side', text: 'Provider keys are stored encrypted on the server or read from its environment, and never sent to the browser.' },
              { icon: ShieldCheck, title: 'Owner controls', text: 'The first account owns the workspace. Features that run commands on the server are limited to the owner.' },
            ].map(({ icon: Icon, title, text }) => (
              <div key={title} className="rounded-2xl border border-border dark:border-border-dark p-6">
                <Icon className="h-5 w-5 text-accent" aria-hidden="true" />
                <h3 className="mt-4 text-base font-semibold">{title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-text-secondary dark:text-text-dark-secondary">{text}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Final CTA */}
        <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
          <div className="rounded-3xl bg-surface-secondary dark:bg-surface-dark-secondary border border-border dark:border-border-dark px-6 py-14 text-center sm:px-12">
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">Start working with Dabba</h2>
            <p className="mx-auto mt-3 max-w-xl text-text-secondary dark:text-text-dark-secondary">
              Create an account and send your first message in under a minute.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <button onClick={onSignup} className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-accent px-5 text-sm font-semibold text-white hover:bg-accent-hover transition-colors sm:w-auto">
                Create your account <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </button>
              <button onClick={onLogin} className="inline-flex h-11 w-full items-center justify-center rounded-xl px-5 text-sm font-semibold text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors sm:w-auto">
                I already have an account
              </button>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border dark:border-border-dark">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-4 py-8 text-sm text-text-tertiary dark:text-text-dark-tertiary sm:flex-row sm:px-6">
          <span className="flex items-center gap-2">
            <img src={logo} alt="" className="h-5 w-5 object-contain" /> Dabba
          </span>
          <span>© {new Date().getFullYear()} Dabba</span>
        </div>
      </footer>
    </div>
  )
}
