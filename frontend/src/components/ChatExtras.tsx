import { useEffect, useState, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { apiClient, type ChatShare, type SavedChatMessage, type SharedChat } from '@/api/client'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import type { Conversation } from '@/types'

const action = 'rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface-secondary dark:border-border-dark dark:hover:bg-surface-dark-tertiary disabled:opacity-50'

function ChatDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useDialogFocus(true, onClose)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3">
      <div ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        className="max-h-[90dvh] w-full max-w-2xl overflow-auto rounded-2xl border border-border bg-surface p-4 shadow-xl dark:border-border-dark dark:bg-surface-dark-secondary sm:p-6">
        <div className="mb-4 flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold">{title}</h2>
          <button type="button" className={action} aria-label="Close" onClick={onClose}><X size={16} /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function SavedMessagesDialog({ items, loading, error, onClose, onOpen, onRemove }: {
  items: SavedChatMessage[]
  loading: boolean
  error: string
  onClose: () => void
  onOpen: (item: SavedChatMessage) => void
  onRemove: (item: SavedChatMessage) => void
}) {
  return (
    <ChatDialog title="Saved messages" onClose={onClose}>
      {error && <p role="alert" className="mb-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {loading && <p role="status" className="text-sm">Loading saved messages…</p>}
      {!loading && !error && !items.length && <p className="text-sm text-text-secondary dark:text-text-dark-secondary">Save a message from its action bar to find it here.</p>}
      <ul className="space-y-2">
        {items.map(item => (
          <li key={`${item.conversation_id}/${item.message_id}`} className="flex items-center gap-3 rounded-xl border border-border p-2 dark:border-border-dark">
            <button type="button" onClick={() => onOpen(item)} className="min-w-0 flex-1 rounded-lg p-2 text-left hover:bg-surface-secondary dark:hover:bg-surface-dark-tertiary">
              <span className="block truncate text-sm font-medium">{item.title}</span>
              <span className="block truncate text-xs text-text-secondary dark:text-text-dark-secondary">{item.snippet}</span>
            </button>
            <button type="button" className={action} onClick={() => onRemove(item)}>Remove</button>
          </li>
        ))}
      </ul>
    </ChatDialog>
  )
}

function shareUrl(id: string) {
  return new URL(`/share/${id}`, window.location.origin).href
}

export function ShareChatDialog({ chatId, loadPreview, onClose }: {
  chatId: string
  loadPreview: (id: string) => Promise<Conversation>
  onClose: () => void
}) {
  const [chat, setChat] = useState<Conversation | null>(null)
  const [links, setLinks] = useState<ChatShare[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [link, setLink] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [preview, setPreview] = useState(false)
  const messages = chat?.messages.filter(message => message.role !== 'system' && message.content.trim() && !message.error && !message.recoveryRequestId && !message.generatedFiles?.length) ?? []

  useEffect(() => {
    let active = true
    Promise.all([loadPreview(chatId), apiClient.chatShares(chatId)])
      .then(([conversation, shares]) => {
        if (active) { setChat(conversation); setLinks(shares) }
      })
      .catch(err => { if (active) setError((err as Error).message) })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [chatId, loadPreview])

  const create = async () => {
    if (chat?.revision === undefined) return
    setBusy(true)
    setError('')
    try {
      const shared = await apiClient.createChatShare(chatId, selected, chat.revision)
      setLink(shareUrl(shared.id))
      setLinks(current => [shared, ...current])
      setPreview(false)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (id: string) => {
    setBusy(true)
    setError('')
    try {
      await apiClient.revokeChatShare(chatId, id)
      setLinks(current => current.filter(item => item.id !== id))
      setLink(current => current === shareUrl(id) ? '' : current)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <ChatDialog title="Share chat" onClose={onClose}>
      <p className="mb-3 text-sm text-text-secondary dark:text-text-dark-secondary">Anyone with the link can see the chat title and selected message text. Attachments and reasoning details are excluded.</p>
      {error && <p role="alert" className="mb-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {busy && !chat && <p role="status" className="text-sm">Loading sharing preview…</p>}
      {chat && (
        <>
          <p className="mb-2 break-words text-sm font-semibold">{chat.title}</p>
          <div className="max-h-60 space-y-2 overflow-y-auto rounded-xl border border-border p-2 dark:border-border-dark">
            {(preview ? messages.filter(message => selected.includes(message.id)) : messages).map(message => (
              <label key={message.id} className="flex items-start gap-2 rounded-lg bg-surface-secondary p-2 text-sm dark:bg-surface-dark-tertiary">
                {!preview && <input type="checkbox" className="mt-1 shrink-0" checked={selected.includes(message.id)}
                  disabled={selected.length >= 50 && !selected.includes(message.id)}
                  onChange={event => setSelected(current => event.target.checked ? [...current, message.id] : current.filter(id => id !== message.id))} />}
                <span className="min-w-0">
                  <span className="block font-semibold">{message.role === 'user' ? 'You' : 'Dabba'}</span>
                  <span className={`block whitespace-pre-wrap break-words ${preview ? '' : 'line-clamp-2'}`}>{message.content}</span>
                </span>
              </label>
            ))}
            {!messages.length && <p className="p-2 text-sm">This chat has no shareable text yet.</p>}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {preview && <button type="button" className={action} disabled={busy} onClick={() => setPreview(false)}>Back to selection</button>}
            <button type="button" className={action} disabled={busy || !selected.length || chat.revision === undefined}
              onClick={() => preview ? void create() : setPreview(true)}>{preview ? 'Create public link' : 'Preview selection'}</button>
          </div>
        </>
      )}
      {link && (
        <label className="mt-4 block text-sm font-semibold">Share link
          <input className="mt-1 w-full rounded-lg border border-border bg-transparent p-2 font-normal dark:border-border-dark" readOnly value={link} onFocus={event => event.currentTarget.select()} />
        </label>
      )}
      {!!links.length && (
        <ul className="mt-4 space-y-2" aria-label="Active share links">
          {links.map(item => (
            <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <a href={shareUrl(item.id)} target="_blank" rel="noopener noreferrer" className="text-accent underline">{new Date(item.created_at).toLocaleString()}</a>
              <button type="button" className={action} disabled={busy} onClick={() => void revoke(item.id)}>Revoke link</button>
            </li>
          ))}
        </ul>
      )}
    </ChatDialog>
  )
}

export function SharedChatPage({ id }: { id: string }) {
  const [chat, setChat] = useState<SharedChat | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    apiClient.publicChatShare(id, controller.signal)
      .then(data => { if (!controller.signal.aborted) setChat(data) })
      .catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [id])
  return (
    <main className="h-full overflow-y-auto p-4 sm:p-8">
      <div className="mx-auto max-w-3xl space-y-4">
        <a className="font-semibold text-accent" href="/">Dabba</a>
        <h1 className="break-words text-2xl font-semibold">{chat?.title ?? 'Shared chat'}</h1>
        {error ? <p role="alert">This shared chat is unavailable.</p> : !chat && <p role="status">Loading shared chat…</p>}
        {chat?.messages.map((message, index) => (
          <article key={index} className="rounded-xl border border-border p-4 dark:border-border-dark">
            <h2 className="mb-2 text-sm font-semibold">{message.role === 'user' ? 'User' : 'Dabba'}</h2>
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          </article>
        ))}
      </div>
    </main>
  )
}
