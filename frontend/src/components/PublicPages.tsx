import { Fragment, type ReactNode } from 'react'
import { ArrowLeft, ArrowUpRight, Warning } from '@phosphor-icons/react'
import { ThemeToggle } from '@/components/ThemeToggle'
import { LEGAL_REVIEWED, PRIVACY, TERMS, type LegalBlock } from '@/content/legal'
import { cn } from '@/lib/utils'
import logo from '../icon.svg'

const FOCUS = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--lp-ink)]'

/** Page chrome shared by the legal pages and the 404: landing page look, with a theme toggle. */
function PublicShell({ onHome, wide, children }: { onHome: () => void; wide?: boolean; children: ReactNode }) {
  return (
    <div className="lp-theme h-full overflow-y-auto overflow-x-hidden bg-[var(--lp-page)] font-sans text-[var(--lp-ink)]">
      <div className="px-3 py-3 sm:px-4 sm:py-4">
        <div className={cn('mx-auto rounded-[32px] bg-[var(--lp-card)] p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)] sm:p-6', wide ? 'max-w-[1100px]' : 'max-w-[720px]')}>
          <header className="flex items-center justify-between gap-4">
            <button type="button" onClick={onHome} aria-label="Dabba home" className={cn('flex items-center gap-2 rounded-full', FOCUS)}>
              <img src={logo} alt="" width={30} height={30} className="h-[30px] w-[30px] object-contain" />
              <span className="font-display text-[20px] font-semibold tracking-[-0.03em]">Dabba</span>
            </button>
            <ThemeToggle />
          </header>
          <main id="main" className="px-1 pb-8 pt-10 sm:px-6 sm:pt-14">{children}</main>
        </div>
        <p className="mx-auto max-w-[1100px] px-4 py-6 text-center text-[13px] text-[var(--lp-muted)]">© {new Date().getFullYear()} Dabba</p>
      </div>
    </div>
  )
}

function BackHome({ onHome, label = 'Back to home' }: { onHome: () => void; label?: string }) {
  return (
    <button
      type="button"
      onClick={onHome}
      className={cn(
        'inline-flex items-center gap-2 rounded-full bg-[var(--lp-btn)] px-5 py-3 text-[15px] font-semibold text-[var(--lp-btn-text)]',
        'transition-transform duration-300 hover:-translate-y-0.5 active:translate-y-0',
        FOCUS,
      )}
    >
      <ArrowLeft size={18} weight="bold" aria-hidden="true" /> {label}
    </button>
  )
}

/** Highlights [PLACEHOLDER] tokens so unfinished details are easy to spot. */
function Text({ children }: { children: string }) {
  return (
    <>
      {children.split(/(\[[A-Z_]{3,}(?::[^\]]*)?\])/g).map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded bg-[#ffe4d8] px-1 text-[#7a2a0c] dark:bg-[#ff5b23]/20 dark:text-[#ffb59a]">{part}</mark>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  )
}

function Block({ block }: { block: LegalBlock }) {
  if (typeof block === 'string') {
    return <p className="text-[16px] leading-[1.75] text-[var(--lp-muted)]"><Text>{block}</Text></p>
  }
  return (
    <ul className="space-y-2.5">
      {block.map(item => (
        <li key={item} className="flex gap-3 text-[16px] leading-[1.7] text-[var(--lp-muted)]">
          <span className="mt-[11px] h-1.5 w-1.5 flex-shrink-0 rounded-full bg-[#FF5B23]" aria-hidden="true" />
          <span><Text>{item}</Text></span>
        </li>
      ))}
    </ul>
  )
}

/**
 * Privacy policy and terms, rendered from content/legal.ts: a contents list,
 * numbered sections and a link to the other document. The wording needs legal
 * review before it is final (LEGAL_REVIEWED in content/legal.ts).
 */
export function LegalPage({ kind, onHome, onSwitch }: { kind: 'privacy' | 'terms'; onHome: () => void; onSwitch?: (kind: 'privacy' | 'terms') => void }) {
  const doc = kind === 'privacy' ? PRIVACY : TERMS
  const other = kind === 'privacy' ? 'terms' : 'privacy'
  const otherTitle = kind === 'privacy' ? 'Terms of use' : 'Privacy policy'

  const contents = (
    <ol className="space-y-1">
      {doc.sections.map((section, i) => (
        <li key={section.id}>
          <a
            href={`#${section.id}`}
            className={cn('flex gap-3 rounded-lg px-2 py-1.5 text-[14px] text-[var(--lp-muted)] hover:bg-[var(--lp-soft)] hover:text-[var(--lp-ink)]', FOCUS)}
          >
            <span className="w-5 flex-shrink-0 tabular-nums text-[var(--lp-accent-text)]">{i + 1}</span>
            {section.title}
          </a>
        </li>
      ))}
    </ol>
  )

  return (
    <PublicShell onHome={onHome} wide>
      <div className="grid grid-cols-1 gap-10 lg:grid-cols-[240px_1fr] lg:gap-16">
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <details className="group rounded-2xl bg-[var(--lp-soft)] p-4 lg:hidden">
            <summary className={cn('cursor-pointer list-none rounded text-[14px] font-semibold [&::-webkit-details-marker]:hidden', FOCUS)}>On this page</summary>
            <nav aria-label="On this page" className="mt-3">{contents}</nav>
          </details>
          <nav aria-label="On this page" className="hidden lg:block">
            <p className="mb-3 px-2 text-[13px] font-semibold">On this page</p>
            {contents}
          </nav>
        </aside>

        <article className="max-w-[720px]">
          <p className="inline-flex items-center gap-2 rounded-full border border-[var(--lp-line)] bg-[var(--lp-card)] px-3 py-1 text-[13px] font-medium text-[var(--lp-ink-2)]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#FF5B23]" aria-hidden="true" />
            Legal
          </p>
          <h1 className="mt-5 font-display text-[44px] font-semibold leading-[1.02] tracking-[-0.045em] text-balance sm:text-[64px]">{doc.title}</h1>
          <p className="mt-4 text-[18px] leading-relaxed text-[var(--lp-muted)]">{doc.summary}</p>
          <p className="mt-3 text-[14px] text-[var(--lp-muted)]">Last updated: <Text>{doc.updated}</Text></p>

          {!LEGAL_REVIEWED && (
            <div role="note" className="mt-6 flex gap-3 rounded-2xl border border-[#FF5B23]/30 bg-[#FF5B23]/10 p-4 text-[14px] leading-relaxed text-[var(--lp-ink-2)]">
              <Warning size={20} weight="fill" className="mt-0.5 flex-shrink-0 text-[var(--lp-accent-text)]" aria-hidden="true" />
              <p>
                This is a draft that describes how Dabba works. It has not yet been reviewed by legal counsel, and the highlighted items are still to be completed.
              </p>
            </div>
          )}

          <div className="mt-12 space-y-12">
            {doc.sections.map((section, i) => (
              <section key={section.id} id={section.id} aria-labelledby={`${section.id}-title`} className="scroll-mt-6">
                <h2 id={`${section.id}-title`} className="flex gap-4 font-display text-[26px] font-semibold leading-tight tracking-[-0.03em] sm:text-[30px]">
                  <span className="mt-1 w-7 flex-shrink-0 text-[16px] tabular-nums text-[var(--lp-accent-text)]">{String(i + 1).padStart(2, '0')}</span>
                  {section.title}
                </h2>
                <div className="mt-4 space-y-4 sm:pl-11">
                  {section.blocks.map((block, index) => <Block key={index} block={block} />)}
                </div>
              </section>
            ))}
          </div>

          <hr className="my-12 border-[var(--lp-line)]" />
          <div className="flex flex-wrap items-center justify-between gap-4">
            <BackHome onHome={onHome} />
            {onSwitch ? (
              <button
                type="button"
                onClick={() => onSwitch(other)}
                className={cn('group inline-flex items-center gap-1.5 rounded-full px-1 py-2 text-[15px] font-semibold', FOCUS)}
              >
                {otherTitle}
                <ArrowUpRight size={18} weight="bold" aria-hidden="true" className="transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
              </button>
            ) : null}
          </div>
        </article>
      </div>
    </PublicShell>
  )
}

/** Branded 404 for unknown public addresses. */
export function NotFoundPage({ onHome }: { onHome: () => void }) {
  return (
    <PublicShell onHome={onHome}>
      <p className="font-display text-[15px] font-semibold text-[var(--lp-accent-text)]">404</p>
      <h1 className="mt-2 font-display text-[44px] font-semibold leading-[1.02] tracking-[-0.045em] text-balance sm:text-[56px]">This page doesn't exist</h1>
      <p className="mt-4 max-w-md text-[17px] leading-relaxed text-[var(--lp-muted)]">
        The address may be mistyped, or the page may have moved. Head back to the home page to keep going.
      </p>
      <div className="mt-8"><BackHome onHome={onHome} label="Go to the home page" /></div>
    </PublicShell>
  )
}
