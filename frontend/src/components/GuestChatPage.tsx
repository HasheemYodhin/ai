import { lazy, Suspense, useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowUp, Sparkle, LockSimple, WarningCircle } from '@phosphor-icons/react'
import { apiClient } from '@/api/client'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import { loadMarkdownRenderer } from '@/lib/markdownRenderer'
import { cn } from '@/lib/utils'
import logo from '../icon.svg'

const MarkdownRenderer = lazy(loadMarkdownRenderer)

/**
 * Free guest chat at /try for signed-out visitors.
 *
 * Visitors get a few prompts (5 by default, enforced by the server) with one
 * fixed model that is shown only as "Auto". Asking for one more opens a sign
 * up / log in prompt. The chat is kept in this browser so a refresh doesn't
 * lose it; it isn't saved to an account.
 */

const EASE = 'ease-[cubic-bezier(0.22,1,0.36,1)]'
const GUEST_ID_KEY = 'dabba-guest-id'
const GUEST_CHAT_KEY = 'dabba-guest-chat'

const STARTERS = [
  'Explain how HTTPS keeps data private, in simple terms.',
  'Write a Python function that removes duplicates from a list and keeps the order.',
  'Plan a productive week for me with a simple daily schedule.',
]

interface GuestMessage {
  role: 'user' | 'assistant'
  content: string
}

/** A stable random id for this browser; the server counts prompts against it. */
function getGuestId(): string {
  try {
    const existing = localStorage.getItem(GUEST_ID_KEY)
    if (existing && /^[A-Za-z0-9_-]{8,64}$/.test(existing)) return existing
    const id = `guest_${crypto.randomUUID().replace(/-/g, '')}`
    localStorage.setItem(GUEST_ID_KEY, id)
    return id
  } catch {
    return `guest_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`
  }
}

function loadSavedChat(): GuestMessage[] {
  try {
    const saved = JSON.parse(localStorage.getItem(GUEST_CHAT_KEY) ?? '[]')
    return Array.isArray(saved) ? saved.filter(m => (m?.role === 'user' || m?.role === 'assistant') && typeof m.content === 'string') : []
  } catch {
    return []
  }
}

const GUEST_IMPORT_KEY = 'dabba-offer-guest-import'

export function readPendingGuestImport(): GuestMessage[] {
  try {
    return sessionStorage.getItem(GUEST_IMPORT_KEY) === '1' ? loadSavedChat() : []
  } catch {
    return []
  }
}

export function dismissGuestImport() {
  try { sessionStorage.removeItem(GUEST_IMPORT_KEY) } catch { /* browser storage unavailable */ }
}

interface GuestChatPageProps {
  onLogin: () => void
  onSignup: () => void
  onHome: () => void
}

export function GuestChatPage({ onLogin, onSignup, onHome }: GuestChatPageProps) {
  const [guestId] = useState(getGuestId)
  const [messages, setMessages] = useState<GuestMessage[]>(loadSavedChat)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [copyStatus, setCopyStatus] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [remaining, setRemaining] = useState<number | null>(null)
  const [limit, setLimit] = useState(5)
  const [available, setAvailable] = useState(true)
  const [gateOpen, setGateOpen] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const gateRef = useDialogFocus(gateOpen, () => setGateOpen(false))

  // Server is the source of truth for how many prompts are left.
  useEffect(() => {
    const controller = new AbortController()
    apiClient.guestStatus(guestId, controller.signal)
      .then(status => { setRemaining(status.remaining); setLimit(status.limit); setAvailable(status.available) })
      .catch(() => { /* status is informational; sending still checks the limit */ })
    return () => controller.abort()
  }, [guestId])

  useEffect(() => {
    try { localStorage.setItem(GUEST_CHAT_KEY, JSON.stringify(messages)) } catch { /* storage full or blocked */ }
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, sending])

  // `history` lets retry resend from a trimmed conversation without waiting
  // for the state update to land.
  const send = useCallback(async (text: string, history: GuestMessage[] = messages) => {
    const prompt = text.trim()
    if (!prompt || sending) return
    // Out of free prompts: ask to sign up instead of sending.
    if (remaining === 0) {
      setGateOpen(true)
      return
    }
    const next: GuestMessage[] = [...history, { role: 'user', content: prompt }]
    setMessages(next)
    setInput('')
    setError(null)
    setSending(true)
    try {
      // Show the reply as it streams in: the assistant bubble appears with
      // the first piece of text and grows from there.
      let reply = ''
      const onDelta = (piece: string) => {
        reply += piece
        setMessages([...next, { role: 'assistant', content: reply }])
      }
      // Only the recent turns go to the server (it accepts up to 20 messages).
      const result = await apiClient.guestChat(guestId, next.slice(-20), onDelta)
      setRemaining(result.remaining)
      if (result.limitReached) {
        setMessages(history) // the prompt wasn't answered; keep it in the box instead
        setInput(prompt)
        setGateOpen(true)
      } else if (result.error) {
        setError(result.error)
      }
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSending(false)
    }
  }, [guestId, messages, remaining, sending])

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    void send(input)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send(input)
    }
  }

  // Retry the last prompt after an error, dropping any partial reply it got.
  const retry = () => {
    let lastUser = messages.length - 1
    while (lastUser >= 0 && messages[lastUser].role !== 'user') lastUser -= 1
    if (lastUser < 0) return
    const prompt = messages[lastUser].content
    void send(prompt, messages.slice(0, lastUser))
  }

  const continueToAccount = (navigate: () => void) => {
    if (messages.length && !sending) {
      try { sessionStorage.setItem(GUEST_IMPORT_KEY, '1') } catch { /* browser storage unavailable */ }
    }
    navigate()
  }

  const copyTranscript = async () => {
    try {
      await navigator.clipboard.writeText(messages.map(message =>
        `${message.role === 'user' ? 'You' : 'Dabba'}\n${message.content}`
      ).join('\n\n'))
      setCopyStatus('Conversation copied.')
    } catch {
      setCopyStatus('Could not copy the conversation. You can select and copy the messages.')
    }
  }

  const outOfPrompts = remaining === 0

  return (
    <div className="flex h-full flex-col bg-surface text-text-primary dark:bg-[#000000] dark:text-text-dark-primary">
      {/* Header */}
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 dark:border-[#272727] sm:px-6">
        <div className="flex items-center gap-3">
          <button onClick={onHome} aria-label="Dabba home" className="flex items-center gap-2">
            <img src={logo} alt="" className="h-6 w-6 object-contain" />
            <span className="title-3 hidden sm:inline">Dabba</span>
          </button>
          {/* The model is fixed for guests and deliberately not named. */}
          <span title="Dabba picks the model for you" className="flex items-center gap-1 rounded-lg border border-border px-2 py-1 caption-4 text-text-secondary dark:border-[#313131] dark:text-text-dark-secondary">
            <Sparkle size={14} weight="fill" className="text-accent" aria-hidden="true" /> Auto
          </span>
        </div>
        <div className="flex items-center gap-2">
          {messages.length > 0 && (
            <button type="button" disabled={sending} onClick={() => void copyTranscript()}
              className="rounded-lg px-2 py-2 text-xs text-accent disabled:opacity-50">Copy chat</button>
          )}
          <button onClick={() => continueToAccount(onLogin)} className={cn('rounded-lg px-3 py-2 button-sm text-text-secondary hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary transition-colors duration-300', EASE)}>
            Log in
          </button>
          <button onClick={() => continueToAccount(onSignup)} className={cn('rounded-lg bg-accent px-3 py-2 button-sm text-white hover:bg-accent-hover active:scale-[0.98] transition-[background-color,transform] duration-300', EASE)}>
            Sign up
          </button>
        </div>
      </header>

      {copyStatus && <p role="status" className="px-4 py-1 text-xs text-text-secondary">{copyStatus}</p>}
      {/* Messages */}
      <main id="main" ref={listRef} className="flex-1 overflow-y-auto px-4 py-8 sm:px-6">
        <div className="mx-auto max-w-3xl space-y-6">
          {messages.length === 0 && (
            <div className="pt-8 text-center sm:pt-16">
              <h1 className="heading-5 sm:heading-4 text-balance">Try Dabba</h1>
              <p className="body-3 mx-auto mt-3 max-w-md text-pretty text-text-secondary dark:text-text-dark-secondary">
                Ask anything.
              </p>
              <div className="mx-auto mt-8 grid max-w-2xl gap-3 sm:grid-cols-3">
                {STARTERS.map(starter => (
                  <button
                    key={starter}
                    onClick={() => void send(starter)}
                    disabled={sending || !available}
                    className={cn('rounded-xl border border-border p-4 text-left body-6 text-text-secondary hover:bg-surface-secondary hover:text-text-primary disabled:opacity-50 dark:border-[#272727] dark:bg-[#181818] dark:text-text-dark-secondary dark:hover:text-text-dark-primary transition-colors duration-300', EASE)}
                  >
                    {starter}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((message, index) => (
            message.role === 'user' ? (
              <div key={index} className="flex justify-end">
                <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-surface-tertiary px-4 py-2 body-3 dark:bg-[#272727]">{message.content}</p>
              </div>
            ) : (
              <div key={index} className="body-3">
                <Suspense fallback={<p className="whitespace-pre-wrap">{message.content}</p>}>
                  <MarkdownRenderer content={message.content} />
                </Suspense>
              </div>
            )
          ))}

          {/* Loading: a skeleton shaped like a reply, not a spinner. */}
          {sending && messages[messages.length - 1]?.role === 'user' && (
            <div role="status" aria-label="Dabba is replying" className="space-y-2">
              {['w-11/12', 'w-9/12', 'w-6/12'].map(width => (
                <div key={width} className={cn('h-4 animate-pulse rounded bg-surface-tertiary dark:bg-[#272727] motion-reduce:animate-none', width)} />
              ))}
            </div>
          )}

          {error && (
            <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2 body-6 text-red-600 dark:text-red-400">
              <WarningCircle size={18} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
              <span className="flex-1">{error}</span>
              <button onClick={retry} className="body-4 underline">Try again</button>
            </div>
          )}
        </div>
      </main>

      {/* Composer */}
      <div className="px-4 pb-4 sm:px-6">
        <form onSubmit={handleSubmit} className="mx-auto max-w-3xl">
          {!available ? (
            <p className="rounded-xl border border-border px-4 py-3 text-center body-6 text-text-secondary dark:border-[#272727] dark:text-text-dark-secondary">
              Free prompts aren't available right now. <button type="button" onClick={() => continueToAccount(onSignup)} className="body-4 text-accent">Sign up</button> or <button type="button" onClick={() => continueToAccount(onLogin)} className="body-4 text-accent">log in</button> to chat.
            </p>
          ) : (
            <div className="flex items-end gap-2 rounded-2xl border border-border bg-surface p-2 focus-within:border-accent dark:border-[#313131] dark:bg-[#181818]">
              <label htmlFor="guest-input" className="sr-only">Message Dabba</label>
              <textarea
                id="guest-input"
                ref={inputRef}
                rows={1}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                maxLength={8000}
                placeholder={outOfPrompts ? 'Sign up to keep chatting' : 'Ask anything'}
                className="max-h-48 flex-1 resize-none bg-transparent px-2 py-2 body-3 outline-none placeholder:text-text-tertiary dark:placeholder:text-text-dark-tertiary"
              />
              <button
                type="submit"
                disabled={sending || !input.trim()}
                aria-label="Send"
                className={cn('flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-accent text-white hover:bg-accent-hover active:scale-[0.98] disabled:opacity-40 transition-[background-color,transform,opacity] duration-300', EASE)}
              >
                <ArrowUp size={18} weight="bold" aria-hidden="true" />
              </button>
            </div>
          )}
        </form>
      </div>

      {/* Sign up gate, shown when a guest asks for one more prompt than allowed. */}
      {gateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="fixed inset-0" onClick={() => setGateOpen(false)} />
          <div ref={gateRef} role="dialog" aria-modal="true" aria-labelledby="guest-gate-title" tabIndex={-1} className="relative w-full max-w-sm rounded-2xl border border-border bg-surface p-6 text-center dark:border-[#272727] dark:bg-[#181818]">
            <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-lg bg-accent/10 text-accent">
              <LockSimple size={20} aria-hidden="true" />
            </span>
            <h2 id="guest-gate-title" className="heading-6 mt-4">You've used your {limit} free prompts</h2>
            <p className="body-6 mt-2 text-pretty text-text-secondary dark:text-text-dark-secondary">
              Create a free account or log in to keep chatting, choose your own models and save your chats.
            </p>
            <div className="mt-6 flex flex-col gap-2">
              <button onClick={() => continueToAccount(onSignup)} className={cn('rounded-lg bg-accent px-3 py-2 button-md text-white hover:bg-accent-hover active:scale-[0.98] transition-[background-color,transform] duration-300', EASE)}>
                Create your account
              </button>
              <button onClick={() => continueToAccount(onLogin)} className={cn('rounded-lg px-3 py-2 button-md text-text-secondary hover:bg-surface-tertiary hover:text-text-primary dark:text-text-dark-secondary dark:hover:bg-[#272727] dark:hover:text-text-dark-primary transition-colors duration-300', EASE)}>
                Log in
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
