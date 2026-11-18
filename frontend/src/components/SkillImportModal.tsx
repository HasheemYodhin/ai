import { useEffect, useRef, useState } from 'react'
import { X, FileUp, Link2, Loader2 } from 'lucide-react'
import type { Skill } from '@/types'
import { cn } from '@/lib/utils'

interface SkillImportModalProps {
  isOpen: boolean
  onClose: () => void
  onImport: (source: { url?: string; content?: string }) => Promise<Skill>
}

const MAX_FILE_BYTES = 512 * 1024

export function SkillImportModal({ isOpen, onClose, onImport }: SkillImportModalProps) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isOpen) { setUrl(''); setError(null); setBusy(false) }
  }, [isOpen])

  if (!isOpen) return null

  const run = async (source: { url?: string; content?: string }) => {
    setBusy(true)
    setError(null)
    try {
      await onImport(source)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setBusy(false)
    }
  }

  const importFile = async (file: File | undefined) => {
    if (!file) return
    if (file.size > MAX_FILE_BYTES) { setError('The file is larger than 512 KB'); return }
    await run({ content: await file.text() })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in">
      <div className="fixed inset-0" onClick={busy ? undefined : onClose} />

      <div className="relative z-10 m-4 w-full max-w-md overflow-hidden rounded-2xl border border-border bg-surface shadow-xl dark:border-border-dark dark:bg-surface-dark-secondary">
        <div className="flex items-center justify-between px-5 h-14 border-b border-border dark:border-border-dark">
          <h3 className="text-[15px] font-medium text-text-primary dark:text-text-dark-primary">Import a skill</h3>
          <button onClick={onClose} disabled={busy} aria-label="Close" className="p-1.5 rounded-lg text-text-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors">
            <X className="w-4 h-4" strokeWidth={1.5} />
          </button>
        </div>

        <div className="p-5 space-y-5">
          <form
            onSubmit={e => { e.preventDefault(); if (url.trim()) void run({ url: url.trim() }) }}
            className="space-y-2"
          >
            <label htmlFor="skill-url" className="block text-[13px] text-text-secondary dark:text-text-dark-secondary">Link to a SKILL.md file</label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Link2 className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" strokeWidth={1.5} />
                <input
                  id="skill-url"
                  autoFocus
                  value={url}
                  onChange={e => setUrl(e.target.value)}
                  placeholder="https://…/SKILL.md"
                  disabled={busy}
                  className="w-full h-10 pl-9 pr-3 text-[13px] rounded-lg glass-input outline-none focus:border-accent/50 transition-colors"
                />
              </div>
              <button
                type="submit"
                disabled={busy || !url.trim()}
                className="h-10 px-4 rounded-lg bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-[13px] font-medium transition-colors"
              >
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Import'}
              </button>
            </div>
            <p className="text-xs text-text-tertiary dark:text-text-dark-tertiary">GitHub file links work too. A skill's web page does not, use its download link</p>
          </form>

          <div className="flex items-center gap-3 text-xs text-text-tertiary dark:text-text-dark-tertiary">
            <span className="flex-1 border-t border-border dark:border-border-dark" />or<span className="flex-1 border-t border-border dark:border-border-dark" />
          </div>

          <button
            type="button"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); void importFile(e.dataTransfer.files[0]) }}
            className={cn(
              'w-full flex flex-col items-center gap-2 py-8 rounded-xl border border-dashed transition-colors',
              dragging
                ? 'border-accent bg-accent/5'
                : 'border-border dark:border-border-dark hover:bg-surface-secondary dark:hover:bg-surface-dark-tertiary'
            )}
          >
            <FileUp className="w-5 h-5 text-text-tertiary" strokeWidth={1.5} />
            <span className="text-[13px] text-text-secondary dark:text-text-dark-secondary">Choose or drop a SKILL.md file</span>
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".md,.markdown,text/markdown,text/plain"
            className="hidden"
            onChange={e => { void importFile(e.target.files?.[0]); e.target.value = '' }}
          />

          {error && <p role="alert" className="text-[13px] text-red-600 dark:text-red-400">{error}</p>}

          <p className="text-xs leading-5 text-text-tertiary dark:text-text-dark-tertiary">
            Dabba keeps the skill's name, description and instructions. Bundled scripts and reference files are not imported. Check the skill's license before using it
          </p>
        </div>
      </div>
    </div>
  )
}
