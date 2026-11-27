import { useEffect, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from 'react'
import {
  ArrowUpRight, Brain, CalendarCheck, ChatsCircle, Check, FileArrowDown, FlowArrow, FolderSimple, ListChecks, Lock,
  Microphone, Play, Plus, PlugsConnected, Quotes, Robot, ShieldCheck, Handshake, X,
} from '@phosphor-icons/react'
import { LANDING } from '@/content/landing'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import { cn } from '@/lib/utils'
import logo from '../icon.svg'

/**
 * Public landing page for signed out visitors at `/`.
 *
 * Light, editorial SaaS look: off-white page, one large rounded hero card
 * holding the navbar and a two column hero, a gradient media panel with
 * floating glass cards, then features, steps, stats, a quote, plans, FAQ,
 * a closing call to action and the footer. Copy lives in content/landing.ts.
 *
 * Motion is CSS only (`lp-rise`, `lp-float` in globals.css) and switches off
 * under prefers-reduced-motion. The page is always light, whatever the app
 * theme, because the design is built around the off-white background.
 */

interface LandingPageProps {
  onTry: () => void
  onLogin: () => void
  onSignup: () => void
  onNavigate: (path: '/privacy' | '/terms') => void
}

const ICONS = [ChatsCircle, PlugsConnected, CalendarCheck]
// One icon per entry in LANDING.capabilities, in the same order.
const CAPABILITY_ICONS = [FolderSimple, Robot, Handshake, FileArrowDown, Microphone, Brain, ShieldCheck, ListChecks]
const PROVIDER_INITIALS = ['A', 'O', 'G', 'N']

// Shared focus ring: dark outline that passes 3:1 on every surface here.
const FOCUS = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--lp-ink)]'

/** Real href for crawlers and new-tab clicks, client side navigation otherwise. */
function appLink(path: string, go: () => void) {
  return {
    href: path,
    onClick: (e: MouseEvent<HTMLAnchorElement>) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
      e.preventDefault()
      go()
    },
  }
}

/** Staggered entrance; `delay` in ms. */
function rise(delay: number): CSSProperties {
  return { animationDelay: `${delay}ms` }
}

function SectionHeading({ eyebrow, title, text }: { eyebrow: string; title: string; text?: string }) {
  return (
    <div className="max-w-2xl">
      <p className="inline-flex items-center gap-2 rounded-full border border-[var(--lp-line)] bg-[var(--lp-card)] px-3 py-1 text-[13px] font-medium text-[var(--lp-ink-2)]">
        <span className="h-1.5 w-1.5 rounded-full bg-[#FF5B23]" aria-hidden="true" />
        {eyebrow}
      </p>
      <h2 className="mt-5 font-display text-[40px] font-semibold leading-[1.02] tracking-[-0.035em] text-[var(--lp-ink)] sm:text-[56px]">
        {title}
      </h2>
      {text && <p className="mt-4 max-w-xl text-[17px] leading-relaxed text-[var(--lp-muted)]">{text}</p>}
    </div>
  )
}

function AvatarStack({ items, size = 'md' }: { items: string[]; size?: 'sm' | 'md' }) {
  const shades = ['bg-[var(--lp-btn)] text-[var(--lp-btn-text)]', 'bg-[#FF5B23] text-[#141414]', 'bg-[#d9d6d0] text-[#141414]', 'bg-[#3b6cf6] text-white']
  return (
    <span className="flex -space-x-2" aria-hidden="true">
      {items.map((letter, i) => (
        <span
          key={letter + i}
          className={cn(
            'flex items-center justify-center rounded-full border-2 border-[var(--lp-card)] font-semibold',
            size === 'sm' ? 'h-7 w-7 text-[11px]' : 'h-9 w-9 text-[13px]',
            shades[i % shades.length],
          )}
        >
          {letter}
        </span>
      ))}
    </span>
  )
}

function PillButton({ children, className, ...link }: { children: ReactNode; className?: string; href: string; onClick?: (e: MouseEvent<HTMLAnchorElement>) => void }) {
  return (
    <a
      {...link}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-full bg-[var(--lp-btn)] px-6 py-3.5 text-[15px] font-semibold text-[var(--lp-btn-text)]',
        'shadow-[0_1px_0_rgba(255,255,255,0.15)_inset,0_8px_24px_-8px_rgba(20,20,20,0.45)] transition-transform duration-300 hover:-translate-y-0.5 active:translate-y-0',
        FOCUS,
        className,
      )}
    >
      {children}
    </a>
  )
}

// ── Hero media panel ────────────────────────────────────────────────────────

// Demo recording of the guest chat (public/demo). Re-record it with a real
// screen capture by replacing these three files.
// The video has a voiceover; captions in the .vtt match it line for line.
const DEMO = {
  mp4: '/demo/dabba-demo.mp4',
  webm: '/demo/dabba-demo.webm',
  poster: '/demo/dabba-demo-poster.jpg',
  captions: '/demo/dabba-demo.vtt',
}

/** Modal video player: Escape or the close button dismisses it; focus stays inside. */
function DemoDialog({ onClose, onTry }: { onClose: () => void; onTry: () => void }) {
  const panelRef = useDialogFocus(true, onClose)
  const videoRef = useRef<HTMLVideoElement>(null)

  // Start with the voiceover on (the dialog was opened by a click). If the
  // browser still blocks sound, play muted; the controls offer unmute.
  // Under reduced motion, don't start on its own.
  useEffect(() => {
    const video = videoRef.current
    if (!video || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    video.play().catch(() => {
      video.muted = true
      video.play().catch(() => {})
    })
  }, [])
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#141414]/70 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Dabba demo video"
        tabIndex={-1}
        onClick={e => e.stopPropagation()}
        className="w-full max-w-5xl overflow-hidden rounded-[24px] bg-[var(--lp-card)] shadow-[0_40px_80px_-20px_rgba(0,0,0,0.6)] outline-none"
      >
        <div className="flex items-center justify-between gap-4 px-5 py-3">
          <p className="font-display text-[17px] font-semibold tracking-[-0.02em] text-[var(--lp-ink)]">See Dabba in action</p>
          <button type="button" onClick={onClose} aria-label="Close video" className={cn('flex h-9 w-9 items-center justify-center rounded-full bg-[var(--lp-soft)] text-[var(--lp-ink)] hover:bg-[var(--lp-hover)]', FOCUS)}>
            <X size={16} weight="bold" aria-hidden="true" />
          </button>
        </div>
        <video
          ref={videoRef}
          controls
          playsInline
          preload="auto"
          poster={DEMO.poster}
          width={1280}
          height={720}
          className="block aspect-video h-auto w-full bg-[var(--lp-soft)]"
        >
          <source src={DEMO.webm} type="video/webm" />
          <source src={DEMO.mp4} type="video/mp4" />
          <track kind="captions" src={DEMO.captions} srcLang="en" label="English" />
        </video>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <p className="text-[14px] text-[var(--lp-muted)]">Ask a question and watch the answer stream in.</p>
          <a {...appLink('/try', onTry)} className={cn('inline-flex items-center rounded-full bg-[var(--lp-btn)] px-5 py-2.5 text-[14px] font-semibold text-[var(--lp-btn-text)]', FOCUS)}>
            Try it yourself
          </a>
        </div>
      </div>
    </div>
  )
}

function HeroPanel({ onPlay }: { onPlay: () => void }) {
  const { chips, stat, task } = LANDING.panel
  return (
    <div className="lp-light relative min-h-[520px] overflow-hidden rounded-[28px] bg-[radial-gradient(120%_90%_at_20%_10%,#ffd9c7_0%,#ff9a6b_38%,#ff5b23_70%,#c93b0c_100%)] sm:min-h-[600px] lg:min-h-full">
      {/* Product window in the background: the first frame of the demo video. */}
      <div aria-hidden="true" className="absolute inset-x-8 bottom-10 top-28 overflow-hidden rounded-[22px] border border-white/50 bg-white/30 p-2 shadow-[0_30px_60px_-20px_rgba(60,20,0,0.45)] backdrop-blur-sm sm:inset-x-12">
        <img src={DEMO.poster} alt="" width={1280} height={720} loading="lazy" className="h-full w-full rounded-[16px] object-cover object-left-top opacity-95" />
      </div>

      {/* Stat card, top right */}
      <div className="lp-rise absolute right-4 top-4 w-[168px] sm:right-6 sm:top-6 sm:w-[188px]" style={rise(250)}>
        <div className="lp-float rounded-[20px] bg-[var(--lp-card)] p-4 shadow-[0_2px_4px_rgba(0,0,0,0.04),0_18px_40px_-12px_rgba(60,20,0,0.35)]" style={{ animationDelay: '0.4s' }}>
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--lp-muted)]">— {stat.label}</p>
          <p className="mt-1 font-display text-[52px] font-semibold leading-none tracking-[-0.04em] text-[var(--lp-ink)]">{stat.value}</p>
          <p className="mt-2 text-[12.5px] leading-snug text-[var(--lp-muted)]">{stat.caption}</p>
        </div>
      </div>

      {/* Play button, centre: opens the demo video */}
      <button
        type="button"
        onClick={onPlay}
        aria-label="Play the Dabba demo video"
        className={cn(
          'lp-rise absolute left-1/2 top-1/2 flex h-[76px] w-[76px] -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-[var(--lp-card)] text-[var(--lp-ink)]',
          'shadow-[0_0_0_10px_rgba(255,255,255,0.28),0_20px_40px_-10px_rgba(60,20,0,0.5)] transition-transform duration-300 hover:scale-105',
          FOCUS,
        )}
        style={rise(150)}
      >
        <Play size={26} weight="fill" aria-hidden="true" />
      </button>

      {/* Glass prompt chips, staggered */}
      <ul className="absolute left-4 top-[22%] space-y-3 sm:left-6 lg:top-[24%]" aria-label="Example prompts">
        {chips.map((chip, i) => (
          <li key={chip.text} className={cn('lp-rise', i === 1 && 'ml-8 sm:ml-14')} style={rise(350 + i * 120)}>
            <div
              className="lp-float flex items-center gap-2.5 rounded-full border border-white/50 bg-white/70 py-2 pl-2 pr-4 text-[13.5px] font-medium text-[var(--lp-ink)] shadow-[0_10px_30px_-12px_rgba(60,20,0,0.45)] backdrop-blur-md"
              style={{ animationDelay: `${0.9 + i * 0.7}s` }}
            >
              <span className={cn('flex h-6 w-6 items-center justify-center rounded-full text-[var(--lp-btn-text)]', chip.tone === 'orange' ? 'bg-[#FF5B23]' : 'bg-[#3b6cf6]')}>
                <Check size={13} weight="bold" aria-hidden="true" />
              </span>
              {chip.text}
            </div>
          </li>
        ))}
      </ul>

      {/* Scheduled task card, bottom right */}
      <div className="lp-rise absolute bottom-4 right-4 w-[250px] sm:bottom-6 sm:right-6 sm:w-[270px]" style={rise(600)}>
        <div className="lp-float flex items-center gap-3 rounded-[20px] bg-[var(--lp-card)] p-3 shadow-[0_2px_4px_rgba(0,0,0,0.04),0_18px_40px_-12px_rgba(60,20,0,0.35)]" style={{ animationDelay: '1.6s' }}>
          <span className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-[14px] bg-[var(--lp-soft)] text-[var(--lp-ink)]">
            <CalendarCheck size={26} aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="line-clamp-2 text-[13.5px] font-medium leading-snug text-[var(--lp-ink)]">{task.title}<br /><span className="text-[var(--lp-muted)]">{task.schedule}</span></p>
            <div className="mt-1.5 flex items-center justify-between gap-2">
              <p className="text-[14px] font-bold text-[var(--lp-ink)]">{task.status}</p>
              <span className="inline-flex items-center gap-1 rounded-full bg-[var(--lp-btn)] px-2 py-0.5 text-[11.5px] font-semibold text-[var(--lp-btn-text)]">
                <Check size={11} weight="bold" aria-hidden="true" />
                {task.result}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Page ────────────────────────────────────────────────────────────────────

export function LandingPage({ onTry, onLogin, onSignup, onNavigate }: LandingPageProps) {
  const { hero } = LANDING
  const tryLink = appLink('/try', onTry)
  const signupLink = appLink('/signup', onSignup)
  const loginLink = appLink('/login', onLogin)
  const [demoOpen, setDemoOpen] = useState(false)

  return (
    <div className="h-full overflow-y-auto lp-theme overflow-x-hidden bg-[var(--lp-page)] font-sans text-[var(--lp-ink)]">
      <a href="#main" className={cn('sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-full focus:bg-[var(--lp-card)] focus:px-4 focus:py-2', FOCUS)}>
        Skip to content
      </a>

      {/* ── Hero card ─────────────────────────────────────────────────── */}
      <div className="px-3 pt-3 sm:px-4 sm:pt-4">
        <div className="mx-auto max-w-[1408px] rounded-[32px] bg-[var(--lp-card)] p-3 shadow-[0_1px_2px_rgba(0,0,0,0.04)] sm:p-4">
          <header className="flex items-center justify-between gap-4 px-3 py-2 sm:px-5 sm:py-3">
            <a href="/" className={cn('flex items-center gap-2 rounded-full', FOCUS)} aria-label="Dabba home">
              <img src={logo} alt="" width={30} height={30} className="h-[30px] w-[30px]" />
              <span className="font-display text-[20px] font-semibold tracking-[-0.03em]">Dabba</span>
            </a>

            <nav aria-label="Sections" className="hidden items-center lg:flex">
              {LANDING.nav.map((link, i) => (
                <span key={link.href} className="flex items-center">
                  {i > 0 && <span className="mx-3 h-1 w-1 rounded-full bg-[var(--lp-dot)]" aria-hidden="true" />}
                  <a href={link.href} className={cn('rounded-md px-1 text-[14.5px] font-medium text-[var(--lp-ink-2)] transition-colors hover:text-[var(--lp-ink)]', FOCUS)}>
                    {link.label}
                  </a>
                </span>
              ))}
            </nav>

            <div className="flex items-center gap-2 sm:gap-5">
              <ThemeToggle />
              <a {...loginLink} className={cn('rounded-md px-1 text-[14.5px] font-medium text-[var(--lp-ink-2)] hover:text-[var(--lp-ink)]', FOCUS)}>Log in</a>
              <a
                {...signupLink}
                className={cn('inline-flex items-center gap-1.5 rounded-full bg-[var(--lp-btn)] py-2.5 pl-4 pr-4 text-[14px] text-[var(--lp-btn-text)] transition-transform duration-300 hover:-translate-y-0.5 sm:pl-5', FOCUS)}
              >
                <span className="font-semibold">Get started</span>
                <span className="hidden text-[var(--lp-btn-text)] opacity-70 sm:inline">· Sign up</span>
              </a>
            </div>
          </header>

          <main id="main" className="mt-2 grid grid-cols-1 gap-4 lg:grid-cols-[1.05fr_1fr]">
            {/* Left column */}
            <div className="flex flex-col justify-between px-3 pb-4 pt-6 sm:px-6 sm:pt-10 lg:px-8 lg:pb-8">
              <div className="lp-rise flex items-center gap-3" style={rise(0)}>
                <span className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--lp-soft)]">
                  <AvatarStack items={['A', 'G']} size="sm" />
                </span>
                <p className="text-[14px] leading-tight">
                  <span className="block font-semibold">{hero.proofTitle}</span>
                  <a href={hero.proofLink.href} className={cn('rounded text-[var(--lp-muted)] underline decoration-[var(--lp-dot)] underline-offset-4 hover:text-[var(--lp-ink)]', FOCUS)}>
                    {hero.proofLink.label}
                  </a>
                </p>
              </div>

              <h1 className="lp-rise mt-10 font-display text-[clamp(88px,16vw,168px)] font-semibold leading-[0.86] tracking-[-0.06em] lg:text-[clamp(120px,11.5vw,168px)]" style={rise(80)}>
                {hero.headline}
                <sup className="ml-1 align-super text-[max(0.22em,24px)] font-medium tracking-[-0.02em] text-[#FF5B23]">{hero.headlineMark}</sup>
              </h1>

              <div className="lp-rise mt-10" style={rise(160)}>
                <hr className="border-[var(--lp-line)]" />
                <p className="py-6 text-[18px] leading-relaxed text-[var(--lp-muted)] sm:text-[20px]">
                  {hero.subheadline[0]}
                  <br className="hidden sm:block" /> {hero.subheadline[1]}
                </p>
                <hr className="border-[var(--lp-line)]" />
              </div>

              <div className="lp-rise flex flex-wrap items-center gap-4 py-6" style={rise(240)}>
                <AvatarStack items={PROVIDER_INITIALS} />
                <p className="text-[14px] leading-tight">
                  <span className="block font-semibold">{hero.badgeTitle}</span>
                  <span className="text-[var(--lp-muted)]">{hero.badgeText}</span>
                </p>
                <span className="hidden h-9 w-px bg-[var(--lp-line)] sm:block" aria-hidden="true" />
                <p className="flex items-center gap-1.5 text-[15px] font-semibold">
                  <Lock size={18} weight="fill" className="text-[#FF5B23]" aria-hidden="true" />
                  {hero.badgeAside}
                </p>
              </div>

              <div className="lp-rise flex flex-wrap items-center gap-x-6 gap-y-3" style={rise(320)}>
                <PillButton {...tryLink}>{hero.primaryCta}</PillButton>
                <a {...signupLink} className={cn('group inline-flex items-center gap-1.5 rounded-full px-1 py-2 text-[15px] font-semibold', FOCUS)}>
                  {hero.secondaryCta}
                  <ArrowUpRight size={18} weight="bold" aria-hidden="true" className="transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                </a>
              </div>
            </div>

            {/* Right column */}
            <HeroPanel onPlay={() => setDemoOpen(true)} />
          </main>
        </div>
      </div>

      {/* ── Works with ────────────────────────────────────────────────── */}
      <section aria-label="Works with" className="mx-auto max-w-[1408px] px-6 py-12 sm:py-14">
        <ul className="flex flex-wrap items-center justify-center gap-x-10 gap-y-4 sm:justify-between sm:px-6">
          <li className="w-full text-center text-[13px] font-medium text-[var(--lp-muted)] sm:w-auto">Works with models from</li>
          {LANDING.worksWith.map(name => (
            <li key={name} className="font-display text-[22px] font-semibold tracking-[-0.03em] text-[var(--lp-ink)] opacity-60">{name}</li>
          ))}
        </ul>
      </section>

      {/* ── Features ──────────────────────────────────────────────────── */}
      <section id="features" className="mx-auto max-w-[1408px] scroll-mt-6 px-4 py-14 sm:px-8 sm:py-20">
        <SectionHeading eyebrow="Product" title="Everything you need to get work done with AI." />
        <div className="mt-12 grid grid-cols-1 gap-4 md:grid-cols-3">
          {LANDING.features.map((f, i) => {
            const Icon = ICONS[i] ?? FlowArrow
            return (
              <article key={f.title} className="group rounded-[28px] bg-[var(--lp-soft-2)] p-7 transition-transform duration-300 hover:-translate-y-1 sm:p-8">
                <span className={cn('flex h-12 w-12 items-center justify-center rounded-2xl', i === 0 ? 'bg-[#FF5B23] text-[var(--lp-ink)]' : 'bg-[var(--lp-card)] text-[var(--lp-ink)]')}>
                  <Icon size={24} aria-hidden="true" />
                </span>
                <h3 className="mt-16 font-display text-[26px] font-semibold leading-tight tracking-[-0.03em]">{f.title}</h3>
                <p className="mt-3 text-[15.5px] leading-relaxed text-[var(--lp-muted)]">{f.text}</p>
              </article>
            )
          })}
        </div>
      </section>

      {/* ── Capabilities ──────────────────────────────────────────────── */}
      <section id="capabilities" className="mx-auto max-w-[1408px] scroll-mt-6 px-4 py-10 sm:px-8 sm:py-14">
        <SectionHeading eyebrow="Everything included" title="More than a chat box." text="Dabba comes with the tools around the conversation, so work does not leave the workspace." />
        <ul className="mt-12 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {LANDING.capabilities.map((c, i) => {
            const Icon = CAPABILITY_ICONS[i] ?? FlowArrow
            return (
              <li key={c.title} className="rounded-[24px] bg-[var(--lp-card)] p-6 transition-transform duration-300 hover:-translate-y-1">
                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[var(--lp-soft)] text-[var(--lp-ink)]">
                  <Icon size={22} aria-hidden="true" />
                </span>
                <h3 className="mt-8 font-display text-[20px] font-semibold tracking-[-0.02em]">{c.title}</h3>
                <p className="mt-2 text-[14.5px] leading-relaxed text-[var(--lp-muted)]">{c.text}</p>
              </li>
            )
          })}
        </ul>
      </section>

      {/* ── How it works ──────────────────────────────────────────────── */}
      <section id="how-it-works" className="mx-auto max-w-[1408px] scroll-mt-6 px-4 py-14 sm:px-8 sm:py-20">
        <div className="rounded-[32px] bg-[var(--lp-card)] p-7 sm:p-12">
          <SectionHeading eyebrow="How it works" title="From first question to running on its own." />
          <ol className="mt-12 grid grid-cols-1 border-t border-[var(--lp-line)] md:grid-cols-3">
            {LANDING.steps.map((s, i) => (
              <li key={s.title} className={cn('py-8 md:px-8 md:first:pl-0', i > 0 && 'border-t border-[var(--lp-line)] md:border-l md:border-t-0')}>
                <span className="font-display text-[15px] font-semibold text-[var(--lp-accent-text)]">0{i + 1}</span>
                <h3 className="mt-6 font-display text-[24px] font-semibold tracking-[-0.03em]">{s.title}</h3>
                <p className="mt-2 text-[15.5px] leading-relaxed text-[var(--lp-muted)]">{s.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── Models and connectors ─────────────────────────────────────── */}
      <section id="models" className="mx-auto max-w-[1408px] scroll-mt-6 px-4 py-10 sm:px-8 sm:py-14">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="rounded-[32px] bg-[var(--lp-card)] p-7 sm:p-10">
            <SectionHeading eyebrow="Models" title={LANDING.models.title} text={LANDING.models.text} />
            <ul className="mt-8 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {LANDING.models.providers.map(p => (
                <li key={p.name} className="flex items-center justify-between gap-3 rounded-2xl bg-[var(--lp-soft)] px-4 py-3">
                  <span className="font-display text-[17px] font-semibold tracking-[-0.02em]">{p.name}</span>
                  <span className="text-right text-[13px] text-[var(--lp-muted)]">{p.family}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-[32px] bg-[var(--lp-soft-2)] p-7 sm:p-10">
            <SectionHeading eyebrow="Connectors" title={LANDING.models.connectorsTitle} text={LANDING.models.connectorsText} />
            <ul className="mt-8 flex flex-wrap gap-2">
              {LANDING.models.connectors.map(name => (
                <li key={name} className="rounded-full bg-[var(--lp-card)] px-4 py-2 text-[14.5px] font-medium">{name}</li>
              ))}
              <li className="rounded-full border border-[var(--lp-line)] px-4 py-2 text-[14.5px] font-medium text-[var(--lp-muted)]">and more</li>
            </ul>
          </div>
        </div>
      </section>

      {/* ── Stats band ────────────────────────────────────────────────── */}
      <section aria-label="Dabba in numbers" className="mx-auto max-w-[1408px] px-4 py-6 sm:px-8">
        <dl className="grid grid-cols-2 gap-px overflow-hidden lp-dark rounded-[32px] bg-[var(--lp-band-line)] lg:grid-cols-4">
          {LANDING.stats.map(s => (
            <div key={s.label} className="bg-[var(--lp-band)] px-6 py-10 sm:px-10 sm:py-14">
              <dt className="text-[14px] text-[var(--lp-muted)]">{s.label}</dt>
              <dd className="mt-2 font-display text-[56px] font-semibold leading-none tracking-[-0.05em] text-[var(--lp-ink)] sm:text-[72px]">{s.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      {/* ── Quote ─────────────────────────────────────────────────────── */}
      <section aria-label="Privacy" className="mx-auto max-w-[1408px] px-4 py-14 sm:px-8 sm:py-20">
        <figure className="mx-auto max-w-4xl text-center">
          <Quotes size={40} weight="fill" className="mx-auto text-[#FF5B23]" aria-hidden="true" />
          <blockquote className="mt-6 font-display text-[28px] font-medium leading-[1.2] tracking-[-0.03em] sm:text-[40px]">
            {LANDING.quote.text}
          </blockquote>
          <figcaption className="mt-6 text-[14px] font-medium text-[var(--lp-muted)]">— {LANDING.quote.source}</figcaption>
        </figure>
      </section>

      {/* ── Security ──────────────────────────────────────────────────── */}
      <section id="security" className="mx-auto max-w-[1408px] scroll-mt-6 px-4 py-14 sm:px-8 sm:py-20">
        <SectionHeading eyebrow="Security" title="Built to be run by you." text="Dabba is self hosted, so the controls sit with the person who runs the server." />
        <ul className="mt-12 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {LANDING.security.map(item => (
            <li key={item.title} className="rounded-[24px] bg-[var(--lp-soft-2)] p-6 sm:p-7">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--lp-btn)] text-[var(--lp-btn-text)]">
                <Check size={18} weight="bold" aria-hidden="true" />
              </span>
              <h3 className="mt-6 font-display text-[20px] font-semibold tracking-[-0.02em]">{item.title}</h3>
              <p className="mt-2 text-[14.5px] leading-relaxed text-[var(--lp-muted)]">{item.text}</p>
            </li>
          ))}
        </ul>
      </section>

      {/* ── Plans ─────────────────────────────────────────────────────── */}
      <section id="plans" className="mx-auto max-w-[1408px] scroll-mt-6 px-4 py-14 sm:px-8 sm:py-20">
        <SectionHeading eyebrow="Plans" title="Start small. Run it your way." text="Model usage is billed by the provider you choose, using your own keys." />
        <div className="mt-12 grid grid-cols-1 gap-4 lg:grid-cols-3">
          {LANDING.plans.map(plan => {
            const link = plan.target === 'try' ? tryLink : signupLink
            return (
              <article
                key={plan.name}
                className={cn(
                  'flex flex-col rounded-[28px] p-7 sm:p-8',
                  plan.featured ? 'bg-[var(--lp-card)] shadow-[0_2px_4px_rgba(0,0,0,0.03),0_24px_48px_-24px_rgba(0,0,0,0.25)] ring-1 ring-[var(--lp-line)]' : 'bg-[var(--lp-soft-2)]',
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <h3 className="font-display text-[28px] font-semibold tracking-[-0.03em]">{plan.name}</h3>
                  <span className={cn('rounded-full px-3 py-1 text-[12.5px] font-semibold', plan.featured ? 'bg-[#FF5B23] text-[var(--lp-ink)]' : 'bg-[var(--lp-card)] text-[var(--lp-ink-2)]')}>
                    {plan.tag}
                  </span>
                </div>
                <p className="mt-3 text-[15.5px] text-[var(--lp-muted)]">{plan.summary}</p>
                <hr className="my-6 border-[var(--lp-line)]" />
                <ul className="flex-1 space-y-3">
                  {plan.points.map(point => (
                    <li key={point} className="flex items-start gap-3 text-[15px]">
                      <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-[var(--lp-btn)] text-[var(--lp-btn-text)]">
                        <Check size={11} weight="bold" aria-hidden="true" />
                      </span>
                      {point}
                    </li>
                  ))}
                </ul>
                <a
                  {...link}
                  className={cn(
                    'mt-8 inline-flex items-center justify-center rounded-full px-5 py-3 text-[15px] font-semibold transition-transform duration-300 hover:-translate-y-0.5',
                    plan.featured ? 'bg-[var(--lp-btn)] text-[var(--lp-btn-text)]' : 'bg-[var(--lp-card)] text-[var(--lp-ink)]',
                    FOCUS,
                  )}
                >
                  {plan.cta}
                </a>
              </article>
            )
          })}
        </div>
      </section>

      {/* ── FAQ ───────────────────────────────────────────────────────── */}
      <section id="faq" className="mx-auto max-w-[1408px] scroll-mt-6 px-4 py-14 sm:px-8 sm:py-20">
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-[1fr_1.4fr]">
          <SectionHeading eyebrow="FAQ" title="Questions, answered." />
          <div className="border-t border-[var(--lp-line)]">
            {LANDING.faqs.map(item => (
              <details key={item.q} className="group border-b border-[var(--lp-line)]">
                <summary className={cn('flex cursor-pointer list-none items-center justify-between gap-6 rounded-lg py-6 [&::-webkit-details-marker]:hidden', FOCUS)}>
                  <h3 className="font-display text-[19px] font-semibold tracking-[-0.02em] sm:text-[21px]">{item.q}</h3>
                  <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-[var(--lp-card)] transition-transform duration-300 group-open:rotate-45">
                    <Plus size={16} weight="bold" aria-hidden="true" />
                  </span>
                </summary>
                <p className="max-w-2xl pb-6 text-[16px] leading-relaxed text-[var(--lp-muted)]">{item.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ─────────────────────────────────────────────────── */}
      <section aria-label="Get started" className="px-3 sm:px-4">
        <div className="relative mx-auto max-w-[1408px] lp-dark overflow-hidden rounded-[32px] bg-[var(--lp-band)] px-7 py-16 text-[var(--lp-ink)] sm:px-14 sm:py-24">
          <div aria-hidden="true" className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-[#FF5B23] opacity-90 blur-[2px]" />
          <div className="relative max-w-2xl">
            <h2 className="font-display text-[44px] font-semibold leading-[0.98] tracking-[-0.045em] sm:text-[72px]">{LANDING.finalCta.title}</h2>
            <p className="mt-6 max-w-lg text-[17px] leading-relaxed text-[var(--lp-muted)]">{LANDING.finalCta.text}</p>
            <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-3">
              <a {...tryLink} className={cn('inline-flex items-center rounded-full bg-[var(--lp-btn)] px-6 py-3.5 text-[15px] font-semibold text-[var(--lp-btn-text)] transition-transform duration-300 hover:-translate-y-0.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white')}>
                {hero.primaryCta}
              </a>
              <a {...signupLink} className="group inline-flex items-center gap-1.5 rounded-full px-1 py-2 text-[15px] font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white">
                {hero.secondaryCta}
                <ArrowUpRight size={18} weight="bold" aria-hidden="true" className="transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ────────────────────────────────────────────────────── */}
      <footer className="mx-auto max-w-[1408px] px-6 pb-10 pt-16 sm:px-10">
        <div className="grid grid-cols-2 gap-10 border-b border-[var(--lp-line)] pb-12 md:grid-cols-[2fr_1fr_1fr_1fr]">
          <div className="col-span-2 md:col-span-1">
            <a href="/" className={cn('inline-flex items-center gap-2 rounded-full', FOCUS)} aria-label="Dabba home">
              <img src={logo} alt="" width={28} height={28} className="h-7 w-7" />
              <span className="font-display text-[20px] font-semibold tracking-[-0.03em]">Dabba</span>
            </a>
            <p className="mt-4 max-w-xs text-[14.5px] leading-relaxed text-[var(--lp-muted)]">The self hosted AI workspace for chat, code and automation.</p>
          </div>
          {[
            { title: 'Product', links: [{ label: 'Try Dabba', ...tryLink }, { label: 'Create an account', ...signupLink }, { label: 'Log in', ...loginLink }] },
            { title: 'Learn', links: LANDING.footerLinks.map(n => ({ label: n.label, href: n.href })) },
            {
              title: 'Legal',
              links: [
                { label: 'Privacy', ...appLink('/privacy', () => onNavigate('/privacy')) },
                { label: 'Terms', ...appLink('/terms', () => onNavigate('/terms')) },
              ],
            },
          ].map(col => (
            <nav key={col.title} aria-label={col.title}>
              <h2 className="text-[13px] font-semibold text-[var(--lp-ink)]">{col.title}</h2>
              <ul className="mt-4 space-y-3">
                {col.links.map(({ label, ...link }) => (
                  <li key={label}>
                    <a {...link} className={cn('rounded text-[14.5px] text-[var(--lp-muted)] hover:text-[var(--lp-ink)]', FOCUS)}>{label}</a>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <p className="mt-8 text-[13px] text-[var(--lp-muted)]">© {new Date().getFullYear()} Dabba. Your chats stay on your Dabba server.</p>
      </footer>

      {demoOpen && <DemoDialog onClose={() => setDemoOpen(false)} onTry={() => { setDemoOpen(false); onTry() }} />}
    </div>
  )
}
